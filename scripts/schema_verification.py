"""Strict PG17 catalogue comparison with one proven binary array-cast rewrite.

No SQL text is stripped. CHECK expression trees retain casts/constants/operators.
Only positions and the display mode of verified binary relabels are nonsemantic.
"""

import argparse
import copy
import json
import re
from pathlib import Path

from sqlalchemy import create_engine, text

TOKEN = re.compile(r'\s*(\{|\}|\(|\)|\[|\]|"(?:\\.|[^"\\])*"|[^\s{}()\[\]]+)')
TYPE_FIELDS = {
    "vartype",
    "consttype",
    "resulttype",
    "array_typeid",
    "element_typeid",
    "typeId",
    "opresulttype",
    "funcresulttype",
}
COLL_FIELDS = {
    "varcollid",
    "constcollid",
    "resultcollid",
    "array_collid",
    "collation",
    "inputcollid",
    "opcollid",
    "funccollid",
}


def parse_tree(source):
    if len(source) > 262144:
        raise ValueError("EXPRESSION_LIMIT")
    tokens = TOKEN.findall(source)
    index = 0

    def item(depth=0):
        nonlocal index
        if depth > 64 or index >= len(tokens):
            raise ValueError("NODE_TREE")
        token = tokens[index]
        index += 1
        if token == "{":
            node = {"node": tokens[index]}
            index += 1
            while tokens[index] != "}":
                key = tokens[index]
                index += 1
                if not key.startswith(":") or key[1:] in node:
                    raise ValueError("NODE_FIELD")
                value = item(depth + 1)
                if key == ":constvalue" and value != "<>" and tokens[index] == "[":
                    value = {"length": value, "datum": item(depth + 1)}
                node[key[1:]] = value
            index += 1
            return node
        if token in {"(", "["}:
            end = ")" if token == "(" else "]"
            values = []
            while tokens[index] != end:
                values.append(item(depth + 1))
            index += 1
            return values
        if token.lstrip("-").isdigit():
            return int(token)
        return token

    try:
        value = item()
        if index != len(tokens) or not isinstance(value, dict):
            raise ValueError("NODE_TRAILING")
        return value
    except (IndexError, RecursionError) as error:
        raise ValueError("NODE_TREE") from error


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def catalog_snapshot(connection, schema="public"):
    version = int(connection.scalar(text("SHOW server_version_num")))
    if version // 10000 != 17:
        raise ValueError("UNSUPPORTED_POSTGRES_MAJOR")
    old = connection.scalar(text("SHOW search_path"))
    connection.execute(text("SELECT set_config('search_path','pg_catalog',true)"))
    try:
        result = {
            "format": "nexus-schema-catalog-v1",
            "major": 17,
            "schema": schema,
            "encoding": connection.scalar(text("SHOW server_encoding")),
            "observed_version": version,
            "observed_search_path": old,
        }
        database = connection.scalar(
            text(
                "SELECT to_jsonb(d) FROM pg_database d WHERE datname=current_database()"
            )
        )
        result["locale"] = {
            k: database.get(k)
            for k in [
                "datlocprovider",
                "datcollate",
                "datctype",
                "datlocale",
                "daticulocale",
                "daticurules",
                "datcollversion",
            ]
        }
        result["locale"]["actual_version"] = connection.scalar(
            text(
                "SELECT pg_database_collation_actual_version(oid) FROM pg_database WHERE datname=current_database()"
            )
        )
        queries = {
            "tables": "SELECT c.relname,c.relkind,c.relpersistence,c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner) owner,c.relacl::text acl FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:schema AND c.relkind IN ('r','p','v','m','S') ORDER BY c.relname",
            "columns": "SELECT c.relname,a.attnum,a.attname,tn.nspname type_schema,t.typname,a.atttypmod,a.attnotnull,a.attidentity,a.attgenerated,a.attisdropped,cn.nspname collation_schema,co.collname,pg_get_expr(d.adbin,d.adrelid,false) default_expression FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_type t ON t.oid=a.atttypid JOIN pg_namespace tn ON tn.oid=t.typnamespace LEFT JOIN pg_collation co ON co.oid=a.attcollation LEFT JOIN pg_namespace cn ON cn.oid=co.collnamespace LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum WHERE n.nspname=:schema AND a.attnum>0 ORDER BY c.relname,a.attnum",
            "indexes": "SELECT c.relname,ic.relname index_name,i.indisunique,i.indisprimary,i.indisvalid,i.indisready,pg_get_indexdef(i.indexrelid) definition FROM pg_index i JOIN pg_class c ON c.oid=i.indrelid JOIN pg_class ic ON ic.oid=i.indexrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:schema ORDER BY c.relname,ic.relname",
            "triggers": "SELECT c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid,false) definition FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:schema AND NOT t.tgisinternal ORDER BY c.relname,t.tgname",
            "functions": "SELECT p.proname,pg_get_function_identity_arguments(p.oid) arguments,pg_get_functiondef(p.oid) definition,pg_get_userbyid(p.proowner) owner,p.proacl::text acl FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=:schema AND p.prokind='f' ORDER BY p.proname,arguments",
        }
        for name, query in queries.items():
            result[name] = [
                dict(r)
                for r in connection.execute(text(query), {"schema": schema}).mappings()
            ]
        checks = (
            connection.execute(
                text(
                    "SELECT k.oid,c.relname,k.conname,k.contype,k.condeferrable,k.condeferred,k.convalidated,k.connoinherit,k.conislocal,k.coninhcount,k.conkey,k.confkey,k.confupdtype,k.confdeltype,k.confmatchtype,pg_get_constraintdef(k.oid,false) definition,pg_get_expr(k.conbin,k.conrelid,false) expression,k.conbin::text tree FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:schema ORDER BY c.relname,k.conname"
                ),
                {"schema": schema},
            )
            .mappings()
            .all()
        )
        result["constraints"] = []
        for raw in checks:
            row = dict(raw)
            oid = row.pop("oid")
            row["dependencies"] = [
                list(v)
                for v in connection.execute(
                    text(
                        "SELECT d.deptype,(pg_identify_object(d.refclassid,d.refobjid,d.refobjsubid)).type,(pg_identify_object(d.refclassid,d.refobjid,d.refobjsubid)).identity FROM pg_depend d WHERE d.classid='pg_constraint'::regclass AND d.objid=:oid ORDER BY 1,2,3"
                    ),
                    {"oid": oid},
                )
            ]
            if row["tree"]:
                row["tree"] = parse_tree(row["tree"])
            result["constraints"].append(row)
        nodes = [n for c in result["constraints"] if c["tree"] for n in walk(c["tree"])]
        types = {
            v
            for n in nodes
            for k, v in n.items()
            if k in TYPE_FIELDS and isinstance(v, int) and v
        }
        types |= {25, 1043, 1009, 1015}
        collations = {
            v
            for n in nodes
            for k, v in n.items()
            if k in COLL_FIELDS and isinstance(v, int) and v
        }
        operators = {n["opno"] for n in nodes if n.get("opno")}
        functions = {
            v
            for n in nodes
            for k, v in n.items()
            if k in {"opfuncid", "funcid", "hashfuncid", "negfuncid"}
            and isinstance(v, int)
            and v
        }
        result["types"] = {
            str(oid): dict(
                connection.execute(
                    text(
                        "SELECT n.nspname,t.typname,t.typlen,t.typbyval,t.typtype,t.typcategory,t.typelem,t.typcollation,t.typbasetype,t.typtypmod,t.typnotnull,t.typinput,t.typoutput,t.typreceive,t.typsend,t.typmodin,t.typmodout,t.typalign,t.typstorage FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE t.oid=:oid"
                    ),
                    {"oid": oid},
                )
                .mappings()
                .one()
            )
            for oid in sorted(types)
        }
        result["collations"] = {
            str(oid): dict(
                connection.execute(
                    text(
                        "SELECT n.nspname,c.collname,c.collprovider,c.collisdeterministic,c.collencoding,c.collcollate,c.collctype,c.collversion,pg_collation_actual_version(c.oid) actual_version FROM pg_collation c JOIN pg_namespace n ON n.oid=c.collnamespace WHERE c.oid=:oid"
                    ),
                    {"oid": oid},
                )
                .mappings()
                .one()
            )
            for oid in sorted(collations)
        }
        result["operators"] = {
            str(oid): dict(
                connection.execute(
                    text(
                        "SELECT n.nspname,o.oprname,o.oprleft,o.oprright,o.oprresult,o.oprcode::oid FROM pg_operator o JOIN pg_namespace n ON n.oid=o.oprnamespace WHERE o.oid=:oid"
                    ),
                    {"oid": oid},
                )
                .mappings()
                .one()
            )
            for oid in sorted(operators)
        }
        result["procedures"] = {
            str(oid): dict(
                connection.execute(
                    text(
                        "SELECT n.nspname,p.proname,pg_get_function_identity_arguments(p.oid) arguments,p.prorettype,p.provolatile,p.proisstrict,p.proleakproof,p.proparallel,p.prosrc,p.probin FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE p.oid=:oid"
                    ),
                    {"oid": oid},
                )
                .mappings()
                .one()
            )
            for oid in sorted(functions)
        }
        result["varchar_to_text_cast"] = dict(
            connection.execute(
                text(
                    "SELECT castsource,casttarget,castfunc,castcontext,castmethod FROM pg_cast WHERE castsource='varchar'::regtype AND casttarget='text'::regtype"
                )
            )
            .mappings()
            .one()
        )
        return result
    finally:
        connection.execute(
            text("SELECT set_config('search_path',:old,true)"), {"old": old}
        )


def normalize(tree, catalog):
    value = copy.deepcopy(tree)
    cast = catalog["varchar_to_text_cast"]
    binary = cast == {
        "castsource": 1043,
        "casttarget": 25,
        "castfunc": 0,
        "castcontext": "i",
        "castmethod": "b",
    }

    def transform(v):
        if isinstance(v, list):
            return [transform(x) for x in v]
        if not isinstance(v, dict):
            return v
        # Source positions do not participate in expression evaluation.
        n = {k: transform(x) for k, x in v.items() if k != "location"}
        if n.get("node") == "RELABELTYPE" and binary:
            source = n["arg"].get(
                "vartype", n["arg"].get("consttype", n["arg"].get("typeId"))
            )
            if (
                source == 1043
                and n.get("resulttype") == 25
                and n.get("resulttypmod") == -1
            ):
                # Preserve the cast and type, canonicalize only its display enum.
                n["relabelformat"] = "verified-binary-varchar-to-text"
        if n.get("node") == "ARRAYCOERCEEXPR" and binary:
            arg, elem = n.get("arg", {}), n.get("elemexpr", {})
            expected_case = {
                "node": "CASETESTEXPR",
                "typeId": 1043,
                "typeMod": -1,
                "collation": 0,
            }
            safe = (
                set(n)
                == {
                    "node",
                    "arg",
                    "elemexpr",
                    "resulttype",
                    "resulttypmod",
                    "resultcollid",
                    "coerceformat",
                }
                and n["resulttype"] == 1009
                and n["resulttypmod"] == -1
                and arg.get("node") == "ARRAYEXPR"
                and arg.get("array_typeid") == 1015
                and arg.get("element_typeid") == 1043
                and arg.get("multidims") == "false"
                and elem.get("node") == "RELABELTYPE"
                and elem.get("arg") == expected_case
                and elem.get("resulttype") == 25
                and elem.get("resulttypmod") == -1
                and elem.get("resultcollid")
                == n["resultcollid"]
                == arg.get("array_collid")
                and all(
                    c.get("node") == "CONST"
                    and c.get("consttype") == 1043
                    and c.get("consttypmod") == -1
                    for c in arg.get("elements", [])
                )
            )
            if safe:
                result = dict(arg)
                result.update(array_typeid=1009, element_typeid=25)
                result["elements"] = [
                    dict(elem, arg=constant) for constant in arg["elements"]
                ]
                return result
        return n

    return transform(value)


def compare(source, restored):
    if (
        source.get("format") != "nexus-schema-catalog-v1"
        or source.get("major") != 17
        or restored.get("major") != 17
    ):
        raise ValueError("UNSUPPORTED_SCHEMA_FORMAT")
    # Builtin cast-related types are captured on both sides, including pinned objects.
    for field in [
        "format",
        "major",
        "observed_version",
        "schema",
        "encoding",
        "locale",
        "tables",
        "columns",
        "indexes",
        "triggers",
        "functions",
        "types",
        "operators",
        "procedures",
        "collations",
        "varchar_to_text_cast",
    ]:
        if source[field] != restored[field]:
            raise ValueError("SCHEMA_MISMATCH:" + field)
    if len(source["constraints"]) != len(restored["constraints"]):
        raise ValueError("CONSTRAINT_SET_MISMATCH")
    rewrites = []
    for left, right in zip(source["constraints"], restored["constraints"], strict=True):
        identity = left["relname"] + "." + left["conname"]
        for key in set(left) | set(right):
            if key not in {"tree", "definition", "expression"} and left.get(
                key
            ) != right.get(key):
                raise ValueError("CONSTRAINT_METADATA_MISMATCH:" + identity)
        if left["contype"] != "c":
            if left != right:
                raise ValueError("CONSTRAINT_DEFINITION_MISMATCH:" + identity)
            continue
        if normalize(left["tree"], source) != normalize(right["tree"], restored):
            raise ValueError("CHECK_EXPRESSION_MISMATCH:" + identity)
        if left["definition"] != right["definition"]:
            rewrites.append(identity)
    return {
        "status": "PASS",
        "constraints": len(source["constraints"]),
        "binary_cast_representations": rewrites,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Private JSON with source_url/restored_url; read-only connections",
    )
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.config.is_symlink() or a.config.stat().st_mode & 0o077:
        raise SystemExit("PRIVATE_CONFIG_REQUIRED")
    config = json.loads(a.config.read_text())
    snapshots = []
    for key in ["source_url", "restored_url"]:
        e = create_engine(
            config[key],
            hide_parameters=True,
            connect_args={"options": "-c default_transaction_read_only=on"},
        )
        try:
            with e.connect() as c:
                snapshots.append(catalog_snapshot(c, config.get("schema", "public")))
        finally:
            e.dispose()
    result = compare(*snapshots)
    a.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - suppress connection/configuration values
        raise SystemExit("SCHEMA_VERIFICATION_FAILED:" + type(error).__name__) from None
