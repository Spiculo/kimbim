// Spike S1: one in-memory IFC model shared by a C++ host and embedded ifcopenshell Python.
//
// Python opens the file; C++ gets the raw IfcParse file pointer and works on the SAME object.
// Each side modifies the model and the other side must observe the change.
// Requires conda-forge ifcopenshell (shared libifcopenshell.parse), NOT the pip wheel.
#include <Python.h>

#include <ifcparse/file.h>
#include <ifcparse/express.h>

#include <iostream>
#include <string>

static PyObject* main_attr(const char* name) {
    return PyObject_GetAttrString(PyImport_AddModule("__main__"), name);
}

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: host <file.ifc>\n";
        return 2;
    }
    Py_Initialize();
    std::string py = "import ifcopenshell, ifcopenshell.api.root\n"
                     "f = ifcopenshell.open(r'''" + std::string(argv[1]) + "''')\n"
                     "ptr = f.file_pointer()\n"
                     "print('[py ] opened, walls:', len(f.by_type('IfcWall')))\n";
    if (PyRun_SimpleString(py.c_str()) != 0) return 1;

    auto* file = reinterpret_cast<ifcopenshell::file*>(PyLong_AsVoidPtr(main_attr("ptr")));
    auto* wall_decl = file->schema()->declaration_by_name("IfcWall");
    auto walls = file->instances_by_type(wall_decl);
    std::cout << "[c++] same model, walls: " << walls.size() << std::endl;
    if (walls.empty()) return 1;

    // C++ edits, Python observes
    walls[0].set_attribute_value("Name", std::string("Renamed from C++"));
    std::cout << "[c++] renamed wall #" << walls[0].id() << std::endl;
    if (PyRun_SimpleString(
            "w = [x for x in f.by_type('IfcWall') if x.Name == 'Renamed from C++']\n"
            "print('[py ] sees C++ rename:', bool(w), w[0].id() if w else None)\n"
            "nw = ifcopenshell.api.root.create_entity(f, ifc_class='IfcWall', name='Created in Python')\n"
            "print('[py ] created wall #%d via ifcopenshell.api' % nw.id())\n") != 0)
        return 1;

    // Python edits, C++ observes
    auto after = file->instances_by_type(wall_decl);
    std::cout << "[c++] sees Python-created wall: walls now " << after.size()
              << (after.size() == walls.size() + 1 ? "  -> SHARED MODEL OK" : "  -> MISMATCH") << std::endl;
    Py_Finalize();
    return after.size() == walls.size() + 1 ? 0 : 1;
}
