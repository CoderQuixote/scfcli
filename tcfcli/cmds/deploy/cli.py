import click
import os
import sys
import uuid
from io import BytesIO
from tcfcli.common.template import Template
from tcfcli.common.user_exceptions import TemplateNotFoundException, InvalidTemplateException, ContextException
from tcfcli.libs.utils.scf_client import ScfClient
from tcfcli.common import tcsam
from tcfcli.common.tcsam.tcsam_macro import TcSamMacro as tsmacro
from zipfile import ZipFile, ZIP_DEFLATED
from tcfcli.libs.utils.cos_client import CosClient

_CURRENT_DIR = '.'
_BUILD_DIR = './.tcf_build'


@click.command()
@click.option('--template-file', '-t', type=click.Path(exists=True), help="TCF template file for deploy")
@click.option('--cos-bucket', '-c', type=str, help="COS bucket name")
@click.option('--function', type=str, help="The name of the function which should be deployed")
@click.option('-f', '--forced', is_flag=True, default=False,
              help="Update the function when it already exists,default false")
@click.option('--skip-event', is_flag=True, default=False,
              help="Keep previous version triggers, do not cover them this time.")
def deploy(template_file, cos_bucket, function, forced, skip_event):
    '''
    Deploy a scf.
    '''

    package = Package(template_file, cos_bucket, function)
    resource = package.do_package()

    deploy = Deploy(resource, forced, skip_event)
    deploy.do_deploy()


class Package(object):

    def __init__(self, template_file, cos_bucket, function):
        self.template_file = template_file
        self.cos_bucket = cos_bucket
        self.check_params()
        template_data = tcsam.tcsam_validate(Template.get_template_data(self.template_file))
        self.resource = template_data.get(tsmacro.Resources, {})
        self.function = function

    def do_package(self):
        for ns in self.resource:
            for func in list(self.resource[ns]):
                if func == tsmacro.Type:
                    continue

                if self.function is not None and func != self.function:
                    self.resource[ns].pop(func)
                    continue

                code_url = self._do_package_core(
                    self.resource[ns][func][tsmacro.Properties].get(tsmacro.CodeUri, "")
                )
                if "cos_bucket_name" in code_url:
                    self.resource[ns][func][tsmacro.Properties]["CosBucketName"] = code_url["cos_bucket_name"]
                    self.resource[ns][func][tsmacro.Properties]["CosObjectName"] = code_url["cos_object_name"]
                    click.secho("Upload function zip file '{}' to COS bucket '{}' success".
                                format(os.path.basename(code_url["cos_object_name"]),
                                       code_url["cos_bucket_name"]), fg="green")
                elif "zip_file" in code_url:
                    self.resource[ns][func][tsmacro.Properties]["LocalZipFile"] = code_url["zip_file"]

        # click.secho("Generate resource '{}' success".format(self.resource), fg="green")
        return self.resource

    def check_params(self):
        if not self.template_file:
            click.secho("FAM Template Not Found", fg="red")
            raise TemplateNotFoundException("Missing option --template-file")

    def _do_package_core(self, func_path):
        zipfile, zip_file_name = self._zip_func(func_path)
        code_url = dict()
        if self.cos_bucket:
            CosClient().upload_file2cos(bucket=self.cos_bucket, file=zipfile.read(),
                                        key=zip_file_name)
            code_url["cos_bucket_name"] = self.cos_bucket
            code_url["cos_object_name"] = "/" + zip_file_name
        else:
            code_url["zip_file"] = os.path.join(os.getcwd(), _BUILD_DIR, zip_file_name)

        return code_url

    def _zip_func(self, func_path):
        buff = BytesIO()
        if not os.path.exists(func_path):
            raise ContextException("Function file or path not found by CodeUri '{}'".format(func_path))

        zip_file_name = str(uuid.uuid1()) + '.zip'
        cwd = os.getcwd()
        os.chdir(func_path)
        with ZipFile(buff, mode='w', compression=ZIP_DEFLATED) as zip_object:
            for current_path, sub_folders, files_name in os.walk(_CURRENT_DIR):
                if current_path == _BUILD_DIR:
                    continue
                for file in files_name:
                    zip_object.write(os.path.join(current_path, file))

        os.chdir(cwd)
        buff.seek(0)
        buff.name = zip_file_name

        if not os.path.exists(_BUILD_DIR):
            os.mkdir(_BUILD_DIR)
        zip_file_path = os.path.join(_BUILD_DIR, zip_file_name)
        # a temporary support for upload func from local zipfile
        with open(zip_file_path, 'wb') as f:
            f.write(buff.read())
            buff.seek(0)
        # click.secho("Compress function '{}' to zipfile '{}' success".format(func_config.name, zip_file_name))
        return buff, zip_file_name


class Deploy(object):
    def __init__(self, resource, forced=False, skip_event=False):
        self.resources = resource
        self.forced = forced
        self.skip_event = skip_event

    def do_deploy(self):
        for ns in self.resources:
            if not self.resources[ns]:
                continue
            click.secho("deploy {ns} begin".format(ns=ns))
            for func in self.resources[ns]:
                if func == tsmacro.Type:
                    continue
                self._do_deploy_core(self.resources[ns][func], func, ns, self.forced, self.skip_event)
            click.secho("deploy {ns} end".format(ns=ns))

    def _do_deploy_core(self, func, func_name, func_ns, forced, skip_event=False):
        err = ScfClient().deploy_func(func, func_name, func_ns, forced)
        if err is not None:
            if sys.version_info[0] == 3:
                s = err.get_message()
            else:
                s = err.get_message().encode("UTF-8")
            click.secho("Deploy function '{name}' failure. Error: {e}.".format(name=func_name,
                                                                               e=s), fg="red")
            if err.get_request_id():
                click.secho("RequestId: {}".format(err.get_request_id().encode("UTF-8")), fg="red")
            return

        click.secho("Deploy function '{name}' success".format(name=func_name), fg="green")
        if not skip_event:
            self._do_deploy_trigger(func, func_name, func_ns)

    def _do_deploy_trigger(self, func, func_name, func_ns):
        proper = func.get(tsmacro.Properties, {})
        events = proper.get(tsmacro.Events, {})

        for trigger in events:
            err = ScfClient().deploy_trigger(events[trigger], trigger, func_name, func_ns)
            if err is not None:
                if sys.version_info[0] == 3:
                    s = err.get_message()
                else:
                    s = err.get_message().encode("UTF-8")

                click.secho(
                    "Deploy trigger '{name}' failure. Error: {e}.".format(name=trigger,
                                                                          e=s), fg="red")
                if err.get_request_id():
                    click.secho("RequestId: {}".format(err.get_request_id().encode("UTF-8")), fg="red")
                continue
            click.secho("Deploy trigger '{name}' success".format(name=trigger), fg="green")
