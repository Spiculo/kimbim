// SPDX-License-Identifier: GPL-3.0-or-later
// Stage 1/2 of the Rust decomposer (docs/19): dump entities, schema attribute names/aggregate kinds
// and attribute values from IfcOpenShell's C++ parser. One tab-separated line per attribute:
//   entity_id  entity_type  attribute_name  aggregate_kind  json_value
// The Rust canonical encoder consumes the values; the Python check compares this with IfcOpenShell.
#include <ifcparse/express.h>
#include <ifcparse/file.h>
#include <ifcparse/instance_data.h>
#include <ifcparse/schema.h>

#include <boost/dynamic_bitset.hpp>
#include <boost/logic/tribool.hpp>

#include <cstdio>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {

void json_string(std::ostream& out, const std::string& text)
{
    out << '"';
    for (unsigned char c : text) {
        switch (c) {
        case '"': out << "\\\""; break;
        case '\\': out << "\\\\"; break;
        case '\n': out << "\\n"; break;
        case '\r': out << "\\r"; break;
        case '\t': out << "\\t"; break;
        case '\b': out << "\\b"; break;
        case '\f': out << "\\f"; break;
        default:
            if (c < 0x20) {
                out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << int(c)
                    << std::dec << std::setfill(' ');
            } else {
                out << char(c);
            }
        }
    }
    out << '"';
}

struct JsonVisitor {
    std::ostream& out;
    explicit JsonVisitor(std::ostream& o) : out(o) {}

    void operator()(ifcopenshell::blank) { out << "null"; }
    void operator()(ifcopenshell::derived) { out << "null"; }
    void operator()(ifcopenshell::empty_aggregate) { out << "[]"; }
    void operator()(ifcopenshell::empty_aggregate_of_aggregate) { out << "[]"; }
    void operator()(int64_t v) { out << v; }
    void operator()(bool v) { out << (v ? "true" : "false"); }
    void operator()(double v) {
        std::ostringstream text;
        text << std::setprecision(17) << v;
        std::string s = text.str();
        // Keep the JSON number a float: Python's json turns "1" into an int, but records.canon must
        // write "1.0" (records.value normalises every IFC REAL through norm_float).
        if (s.find_first_of(".eE") == std::string::npos)
            s += ".0";
        out << s;
    }
    void operator()(const std::string& v) { json_string(out, v); }
    void operator()(const boost::dynamic_bitset<>& v) {
        std::string bits(v.size(), '0');
        for (size_t i = 0; i < v.size(); ++i)
            if (v[i])
                bits[v.size() - 1 - i] = '1';
        json_string(out, bits);
    }
    void operator()(const boost::logic::tribool& v) {
        out << (boost::logic::indeterminate(v) ? "null" : (v ? "true" : "false"));
    }
    void operator()(const ifcopenshell::enumeration_reference& v) {
        const char* name = v.value();
        if (name)
            json_string(out, name);
        else
            out << "null";
    }
    void operator()(const express::base& entity) {
        if (entity.id() == 0) { // a typed value (IfcLabel, IfcReal, ...)
            out << "{\"@t\":";
            json_string(out, entity.declaration().name());
            out << ",\"v\":";
            try {
                entity.get_attribute_value(0).apply_visitor(*this);
            } catch (...) {
                out << "null";
            }
            out << '}';
            return;
        }
        out << "{\"ref\":" << entity.id() << '}';
    }
    template <typename T>
    void operator()(const std::vector<T>& values) {
        out << '[';
        for (size_t i = 0; i < values.size(); ++i) {
            if (i)
                out << ',';
            (*this)(values[i]);
        }
        out << ']';
    }
    template <typename T>
    void operator()(const T&) { out << "null"; }
};

const char* aggregate_name(const ifcopenshell::parameter_type* type)
{
    while (type) {
        if (const auto* aggregation = type->as_aggregation_type()) {
            switch (aggregation->type_of_aggregation()) {
            case ifcopenshell::aggregation_type::array_type: return "ARRAY";
            case ifcopenshell::aggregation_type::bag_type: return "BAG";
            case ifcopenshell::aggregation_type::list_type: return "LIST";
            case ifcopenshell::aggregation_type::set_type: return "SET";
            }
            return "-";
        }
        const auto* named = type->as_named_type();
        if (!named)
            break;
        const auto* declaration = named->declared_type();
        const auto* type_declaration = declaration ? declaration->as_type_declaration() : nullptr;
        if (!type_declaration)
            break;
        type = type_declaration->declared_type();
    }
    return "-";
}

std::string type_tree(const ifcopenshell::parameter_type* type)
{
    if (!type)
        return "?";
    if (const auto* aggregation = type->as_aggregation_type()) {
        return std::string(aggregate_name(aggregation)) + "<"
            + type_tree(aggregation->type_of_element()) + ">";
    }
    if (const auto* named = type->as_named_type()) {
        const auto* declaration = named->declared_type();
        const auto* type_declaration = declaration ? declaration->as_type_declaration() : nullptr;
        if (type_declaration) {
            const auto* inner = type_declaration->declared_type();
            if (inner && inner->as_aggregation_type())
                return type_tree(inner);
        }
        return declaration ? declaration->name() : "?";
    }
    if (const auto* simple = type->as_simple_type()) {
        switch (simple->declared_type()) {
        case ifcopenshell::simple_type::binary_type: return "BINARY";
        case ifcopenshell::simple_type::boolean_type: return "BOOLEAN";
        case ifcopenshell::simple_type::integer_type: return "INTEGER";
        case ifcopenshell::simple_type::logical_type: return "LOGICAL";
        case ifcopenshell::simple_type::number_type: return "NUMBER";
        case ifcopenshell::simple_type::real_type: return "REAL";
        case ifcopenshell::simple_type::string_type: return "STRING";
        default: return "?";
        }
    }
    return "?";
}

} // namespace

int main(int argc, char** argv)
{
    if (argc != 2) {
        std::fprintf(stderr, "usage: ifcdump <model.ifc>\n");
        return 2;
    }
    ifcopenshell::file file(std::string(argv[1]), ifcopenshell::FT_IFCSPF);
    if (!file.good()) {
        std::fprintf(stderr, "cannot open %s\n", argv[1]);
        return 1;
    }
    std::printf("schema\t%s\n", file.schema()->name().c_str());
    // Defined types used by typed values (IfcLabel, IfcCompoundPlaneAngleMeasure...): the Rust
    // decomposer needs the wrapped parameter type to order SET members inside a typed value.
    for (const auto* type : file.schema()->type_declarations()) {
        std::printf("type\t%s\t%s\n", type->name().c_str(),
            type_tree(type->declared_type()).c_str());
    }
    // Entity supertypes let the Rust side tell IfcRoot owners from shared non-rooted entities.
    for (const auto* entity : file.schema()->entities()) {
        const auto* super = entity->supertype();
        std::printf("entity\t%s\t%s\n", entity->name().c_str(), super ? super->name().c_str() : "");
    }
    // Snapshot ids first: value access can populate lazy storage and must not invalidate the
    // iterator we are walking.
    std::vector<uint32_t> ids;
    for (auto it = file.begin(); it != file.end(); ++it)
        ids.push_back(it->first);
    size_t entities = 0;
    for (uint32_t id : ids) {
        express::base entity = file.instance_by_id(int(id));
        if (!entity)
            continue;
        const auto& declaration = entity.declaration();
        const auto* definition = declaration.as_entity();
        if (!definition)
            continue;
        const auto& attributes = definition->all_attributes();
        const auto& derived = definition->derived();
        for (size_t i = 0; i < attributes.size(); ++i) {
            if (i < derived.size() && derived[i])
                continue;
            const auto* attribute = attributes[i];
            std::ostringstream value;
            JsonVisitor visitor(value);
            entity.get_attribute_value(i).apply_visitor(visitor);
            std::printf("%u\t%s\t%s\t%s\t%s\t%s\n", entity.id(), declaration.name().c_str(),
                attribute->name().c_str(),
                aggregate_name(attribute->type_of_attribute()),
                type_tree(attribute->type_of_attribute()).c_str(),
                value.str().c_str());
            std::fflush(stdout);
        }
        ++entities;
    }
    std::fprintf(stderr, "entities\t%zu\n", entities);
    std::fflush(stdout);
    std::fflush(stderr);
    // The IfcOpenShell C++ destructor crashes at exit after value access on Windows (the simple
    // stage-1 dump did not). A one-shot dump does not need it; exit before teardown.
    std::_Exit(0);
}
