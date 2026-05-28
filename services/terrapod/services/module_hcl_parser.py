"""Extract Terraform variable and output declarations from module tarballs."""

import io
import json
import tarfile

import hcl2

from terrapod.logging_config import get_logger

logger = get_logger(__name__)


def extract_module_interface(tarball_bytes: bytes) -> dict:
    """Parse .tf files from a module tarball and extract variable/output blocks.

    Returns {"inputs": [...], "outputs": [...]}.
    Returns {"inputs": [], "outputs": []} on parse failure.
    """
    inputs: list[dict] = []
    outputs: list[dict] = []

    try:
        tf_contents = _read_root_tf_files(tarball_bytes)
        for content in tf_contents:
            parsed = _parse_hcl(content)
            if parsed is None:
                continue
            inputs.extend(_extract_variables(parsed))
            outputs.extend(_extract_outputs(parsed))
    except Exception:
        logger.warning("Failed to extract module interface", exc_info=True)
        return {"inputs": [], "outputs": []}

    return {"inputs": inputs, "outputs": outputs}


def _read_root_tf_files(tarball_bytes: bytes) -> list[str]:
    """Read all .tf files at the root level of the tarball."""
    contents = []
    with tarfile.open(fileobj=io.BytesIO(tarball_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            if "/" in member.name:
                continue
            if not member.name.endswith(".tf"):
                continue
            f = tar.extractfile(member)
            if f is None:
                continue
            contents.append(f.read().decode("utf-8", errors="replace"))
    return contents


def _parse_hcl(content: str) -> dict | None:
    """Parse HCL content, returning None on failure."""
    try:
        return hcl2.loads(content)
    except Exception:
        return None


def _serialize_default(value) -> str | None:
    """Serialize a default value to a JSON-friendly string representation."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _type_to_string(type_val) -> str:
    """Convert a python-hcl2 type representation to a readable string."""
    if type_val is None:
        return "any"
    if isinstance(type_val, str):
        return type_val
    if isinstance(type_val, list) and len(type_val) > 0:
        return str(type_val[0]) if len(type_val) == 1 else str(type_val)
    return str(type_val)


def _extract_variables(parsed: dict) -> list[dict]:
    """Extract variable blocks from parsed HCL."""
    variables = []
    for var_block in parsed.get("variable", []):
        for var_name, var_config in var_block.items():
            has_default = "default" in var_config
            variables.append({
                "name": var_name,
                "type": _type_to_string(var_config.get("type")),
                "description": var_config.get("description", ""),
                "default": _serialize_default(var_config.get("default")) if has_default else None,
                "required": not has_default,
                "sensitive": bool(var_config.get("sensitive", False)),
            })
    return variables


def _extract_outputs(parsed: dict) -> list[dict]:
    """Extract output blocks from parsed HCL."""
    outputs = []
    for out_block in parsed.get("output", []):
        for out_name, out_config in out_block.items():
            outputs.append({
                "name": out_name,
                "description": out_config.get("description", ""),
                "sensitive": bool(out_config.get("sensitive", False)),
            })
    return outputs
