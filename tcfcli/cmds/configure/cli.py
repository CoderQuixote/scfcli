import click
import platform
from tcfcli.help.message import ConfigureHelp as help
from tcfcli.common.user_config import UserConfig
from tcfcli.common.scf_client.scf_report_client import ScfReportClient

version = platform.python_version()
if version >= '3':
    from functools import reduce


def report_info():
    pass


@click.command(short_help=help.GET_SHORT_HELP)
@click.option('--secret-id', is_flag=True, help=help.GET_SECRET_ID)
@click.option('--secret-key', is_flag=True, help=help.GET_SECRET_KEY)
@click.option('--region', is_flag=True, help=help.GET_REGION)
@click.option('--appid', is_flag=True, help=help.GET_APPID)
def get(**kwargs):
    '''
        \b
        Get your account parameters.
        \b
        Common usage:
            \b
            * Get the configured information
              $ scf configure get
        '''
    uc = UserConfig()

    def set_true(k):
        kwargs[k] = True

    bools = [v for k, v in kwargs.items()]
    if not reduce(lambda x, y: bool(x or y), bools):
        list(map(set_true, kwargs))
    attrs = uc.get_attrs(kwargs)
    msg = "{} config:\n".format(UserConfig.API)
    for attr in sorted(attrs):
        attr_value = attrs[attr]
        if attr == "secret-id":
            attr_value = "*" * 32 + attr_value[32:]
        elif attr == "secret-key":
            attr_value = "*" * 28 + attr_value[28:]
        msg += "{} = {}\n".format(attr, attr_value)
    click.secho(msg.strip())


@click.command(short_help=help.SET_SHORT_HELP)
@click.option('--secret-id', help=help.SET_SECRET_ID)
@click.option('--secret-key', help=help.SET_SECRET_KEY)
@click.option('--region', help=help.SET_REGION)
@click.option('--appid', help=help.SET_APPID)
def set(**kwargs):
    '''
        \b
        Configure your account parameters.
        \b
        Common usage:
            \b
            * Configure your account parameters
              $ scf configure set
            \b
            * Modify a configuration item
              $ scf configure set --region ap-shanghai
    '''

    def set_true(k):
        kwargs[k] = True

    uc = UserConfig()
    values = [v for k, v in kwargs.items()]
    if not reduce(lambda x, y: (bool(x) or bool(y)), values):
        list(map(set_true, kwargs))
        attrs = uc.get_attrs(kwargs)
        config = {}
        for attr in sorted(attrs):
            attr_value = attrs[attr]
            if attr == "secret-id":
                attr_value = "*" * 32 + attr_value[32:]
            elif attr == "secret-key":
                attr_value = "*" * 28 + attr_value[28:]
            v = click.prompt(
                text="TencentCloud {}({})".format(attr, attr_value),
                default=attrs[attr],
                show_default=False)
            config[attr] = v
        kwargs = config
    uc.set_attrs(kwargs)
    uc.flush()
    if not reduce(lambda x, y: (bool(x) or bool(y)), values):
        v = click.prompt(text="Allow report information to help us optimize scfcli(Y/n)",
                         default="y",
                         show_default=False)
        if v in ["y", "Y"]:
            client = ScfReportClient()
            client.report()


@click.group(name='configure', short_help=help.SHORT_HELP)
def configure():
    """
        \b
        You need to perform initial configuration and configure the account information in the configuration file of scf cli for subsequent use.
        \b
        Common usage:
            \b
            * Configure your account parameters
              $ scf configure set
            \b
            * Modify a configuration item
              $ scf configure set --region ap-shanghai
            \b
            * Get the configured information
              $ scf configure get
    """


configure.add_command(get)
configure.add_command(set)
