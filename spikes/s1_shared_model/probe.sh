#!/usr/bin/env bash
# Spike S1 helper: inspect the conda-forge IfcOpenShell 0.9 C++/Python API available in the env.
ENV=~/kimcad-s1/env
cd "$ENV/include" || exit 1
grep -n 'class IFC_PARSE_API\|^class \|schema() const\|IfcFile(' ifcparse/file.h | head -12
grep -n 'declaration_by_name' ifcparse/schema.h ifcparse/*.h 2>/dev/null | head -4
grep -n 'class \|std::string name\|const ifcopenshell::declaration& declaration\|id() const\|is_a(' ifcparse/express.h | head -20
"$ENV/bin/python" - <<'EOF'
import ifcopenshell
f = ifcopenshell.file(schema="IFC4")
print([a for a in dir(f) if not a.startswith("__")][:60])
for name in ("wrapped_data", "_wrapped_data", "file", "_file", "storage"):
    try:
        v = object.__getattribute__(f, name)
        print(name, type(v), getattr(v, "this", None))
    except AttributeError:
        pass
print(f.__dict__.keys() if hasattr(f, "__dict__") else "no __dict__")
EOF
