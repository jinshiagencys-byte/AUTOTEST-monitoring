"""A deliberately small Python script contract; no arbitrary generated code.

Scripts are Python modules defining run(ctx) with literal calls to the runtime.
Validation happens both when publishing and before replay. This is not an OS
sandbox; it is an allowlist for the generated language.
"""

import ast


METHODS = {
    "open": ("url",),
    "click": ("target",),
    "type_text": ("target", "text"),
    "assert_text": ("target", "expected"),
    "assert_visible": ("target",),
    "assert_value": ("target", "expected"),
    "assert_url": ("expected",),
    "assert_title": ("expected",),
}
TARGET_KEYS = {"tag", "text", "aria_label", "placeholder", "id", "name", "role"}


def validate_script(source):
    tree = ast.parse(source)
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("Expected only def run(ctx)")
    fn = tree.body[0]
    args = fn.args
    if (fn.name != "run" or fn.decorator_list or fn.returns or
            len(args.args) != 1 or args.args[0].arg != "ctx" or
            args.args[0].annotation or args.defaults or args.kwonlyargs or
            args.vararg or args.kwarg or args.posonlyargs or fn.type_comment):
        raise ValueError("Expected undecorated def run(ctx)")
    if not 2 <= len(fn.body) <= 200:
        raise ValueError("Expected 2 to 200 runtime calls")
    calls = []
    for statement in fn.body:
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            raise ValueError("Only literal ctx.method(...) calls are allowed")
        call = statement.value
        if (not isinstance(call.func, ast.Attribute) or
                not isinstance(call.func.value, ast.Name) or
                call.func.value.id != "ctx" or call.func.attr not in METHODS or call.keywords):
            raise ValueError("Unsupported runtime call")
        method = call.func.attr
        if len(call.args) != len(METHODS[method]):
            raise ValueError("Wrong argument count for " + method)
        values = [ast.literal_eval(arg) for arg in call.args]
        for key, value in zip(METHODS[method], values):
            if key == "target":
                if (not isinstance(value, dict) or not value or
                        set(value) - TARGET_KEYS or not set(value) - {"tag"} or
                        any(not isinstance(v, str) or not v for v in value.values())):
                    raise ValueError("Expected a nonempty semantic target")
            elif not isinstance(value, str):
                raise ValueError("Expected string argument")
        calls.append((method, values))
    if calls[0][0] != "open" or not any(m.startswith("assert_") for m, _ in calls):
        raise ValueError("A script must open its page and contain an assertion")
    return calls


def replay(source, context):
    # Interpret the validated Python calls instead of exec'ing model output.
    for method, values in validate_script(source):
        getattr(context, method)(*values)