# Loops through all TG classes and converts list-type attributes to tuples.
import importlib
import inspect
import os
import re
import types
from pathlib import Path
from importlib import reload

import telegram


def reload_package(package):
    assert hasattr(package, "__package__")
    fn = package.__file__
    fn_dir = os.path.dirname(fn) + os.sep
    module_visit = {fn}
    del fn

    def reload_recursive_ex(module):
        importlib.reload(module)

        for module_child in vars(module).values():
            if isinstance(module_child, types.ModuleType):
                fn_child = getattr(module_child, "__file__", None)
                if (fn_child is not None) and fn_child.startswith(fn_dir):
                    if fn_child not in module_visit:
                        # print("reloading:", fn_child, "from", module)
                        module_visit.add(fn_child)
                        reload_recursive_ex(module_child)

    return reload_recursive_ex(package)


# loop through all classes in the `telegram` module
classes = inspect.getmembers(telegram, inspect.isclass)
for name, _ in classes:
    cls = getattr(telegram, name)

    print("Processing class", name)
    # first adjust the __init__ of the class
    params = inspect.signature(cls.__init__).parameters
    params_to_change = set()
    for param in params.values():
        if "List" in str(param.annotation):
            print("  Converting list-type parameter", param.name, "to Sequence")
            params_to_change.add(param.name)

    if not params_to_change:
        continue

    class_source_file = Path(inspect.getfile(cls))

    _, class_start_line = inspect.getsourcelines(cls)
    class_source = inspect.getsource(cls)
    class_source_lines = class_source.splitlines()
    class_length = len(class_source_lines)

    init_source_lines, init_start_line = inspect.getsourcelines(cls.__init__)
    init_length = len(init_source_lines)
    init_source = inspect.getsource(cls.__init__)

    args_start_line = -1
    attributes_start_line = -1
    # Search "Args:" block in the docstring
    for i, line in enumerate(class_source_lines):
        if line.strip().startswith("Args:"):
            args_start_line = i
        if line.strip().startswith("Attributes:"):
            attributes_start_line = i
        if class_start_line + i == init_start_line:
            break

    # In the "Args:" block replace "List[" by "Sequence["
    for i in range(args_start_line + 1, attributes_start_line):
        whitespaces = -1
        for param in params_to_change:
            if f"{param} (List[" not in class_source_lines[i]:
                continue

            class_source_lines[i] = class_source_lines[i].replace(
                f"{param} (List[", f"{param} (Sequence["
            )
            whitespaces = re.match(r" +", class_source_lines[i]).end() + 4
            j = i + 1
            while class_source_lines[j] and (
                re.match(r"\s+", class_source_lines[j]).end() >= whitespaces
            ):
                j = j + 1

            class_source_lines[
                j - 1
            ] += f"\n\n{whitespaces * ' '}.. versionchanged:: 20.0\n{whitespaces * ' '}    |squenceclassargs|"
            if class_source_lines[j]:
                class_source_lines[j - 1] += "\n"

    # In the "Attributes:" block replace "List[" by "Sequence["
    for i in range(attributes_start_line + 1, class_length):
        whitespaces = -1
        for param in params_to_change:
            if f"{param} (List[" not in class_source_lines[i]:
                continue

            class_source_lines[i] = class_source_lines[i].replace(
                f"{param} (List[", f"{param} (Sequence["
            )
            whitespaces = re.match(r" +", class_source_lines[i]).end() + 4
            j = i + 1
            while class_source_lines[j] and (
                re.match(r"\s+", class_source_lines[j]).end() >= whitespaces
            ):
                j = j + 1

            class_source_lines[
                j - 1
            ] += f"\n\n{whitespaces * ' '}.. versionchanged:: 20.0\n{whitespaces * ' '}    |tupleclassattrs|"
            if class_source_lines[j]:
                class_source_lines[j - 1] += "\n"

    # Adjust type annotations in the __init__ and converts to tuples before assigning to
    # attributes
    for param in params_to_change:
        init_source = init_source.replace(param + ": List", param + ": Sequence")
        init_source = re.sub(
            rf"self\.{param} = ([^ ]*)\n", rf"self.{param} = tuple(\1)\n", init_source
        )
        init_source = re.sub(
            rf"self\.{param} = (.*) or \[\]\n", rf"self.{param} = tuple(\1 or ())\n", init_source
        )

    file_contents = class_source_file.read_text(encoding="utf-8")
    file_contents = file_contents.splitlines()

    # Insert new __init__
    file_contents[
        init_start_line - 1 : init_start_line + init_length - 1
    ] = init_source.splitlines()

    # Insert new docstring
    file_contents[class_start_line - 1 : init_start_line - 2] = class_source_lines[
        : init_start_line - class_start_line - 1
    ]

    i = 0
    while file_contents[i].startswith("#"):
        i += 1
    file_contents[i] += "\nfrom typing import Sequence"

    file_contents = "\n".join(file_contents) + "\n"

    class_source_file.write_text(file_contents, encoding="utf-8")

    # so that the changes are reflected in the module
    reload_package(telegram)
