// Starts `src` with test-only service doubles (an in-memory keyring, optional auth/skill staging) in the isolated
// real-core runners. argv: memory|missing, auth base URL, staged skill, skill file delivery, then the core's own args.
// '' or '-' leaves an option unset ('-' where an argv must be nonempty, as in the app's development core command).
export const isolatedServicesBootstrap = `
import sys, runpy, os
from src.desktop.management import ManagementService
class MemoryKeyring:
    def __init__(self): self.values = {}
    def check(self):
        if os.path.exists(os.path.join(os.environ['HOME'], 'keyring.locked')):
            raise RuntimeError('ephemeral test keyring locked')
    def get_password(self, namespace, name):
        self.check()
        return self.values.get((namespace, name))
    def set_password(self, namespace, name, value):
        self.check()
        self.values[(namespace, name)] = value
    def delete_password(self, namespace, name):
        self.check()
        self.values.pop((namespace, name), None)
if sys.argv[1] == 'memory':
    original = ManagementService.compose.__func__
    backend = MemoryKeyring()
    ManagementService.compose = classmethod(lambda cls, core, **kw: original(cls, core, secret_backend=backend))
base = '' if sys.argv[2] == '-' else sys.argv[2]
if base:
    import src.desktop.codex_accounts as device
    import src.llm.codex_auth as auth
    device.DEVICE_USERCODE_URL = base + '/device/code'
    device.DEVICE_TOKEN_URL = base + '/device/token'
    device.DEVICE_VERIFY_URL = base + '/verify'
    auth.TOKEN_URL = base + '/oauth/token'
stage_skill = '' if sys.argv[3] == '-' else sys.argv[3]
file_delivery = sys.argv[4]
if stage_skill:
    from src.discord.native_tools.registry import NativeToolDispatcher
    dispatch = NativeToolDispatcher.dispatch
    async def staged_dispatch(self, tool_name, tool_input, **kwargs):
        if tool_name == stage_skill or (tool_name == 'invoke_skill' and tool_input.get('name') == stage_skill):
            kwargs['skill_file_delivery'] = file_delivery
        return await dispatch(self, tool_name, tool_input, **kwargs)
    NativeToolDispatcher.dispatch = staged_dispatch
sys.argv = ['src', *sys.argv[5:]]
runpy.run_module('src', run_name='__main__')
`
