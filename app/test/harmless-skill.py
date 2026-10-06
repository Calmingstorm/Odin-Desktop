SKILL_DEFINITION = {
    'name': 'slice4_constant',
    'description': 'Trusted harmless local constant fixture',
    'input_schema': {'type': 'object', 'properties': {}},
}


async def execute(inp, context):
    return 'harmless constant'
