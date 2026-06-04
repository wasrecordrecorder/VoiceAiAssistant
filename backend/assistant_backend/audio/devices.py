from typing import Any

import sounddevice as sd


def _name(value: Any) -> str:
    return str(value).strip()


def list_devices() -> dict:
    devices = sd.query_devices()
    defaults = sd.default.device
    input_default = int(defaults[0]) if defaults and defaults[0] is not None else -1
    output_default = int(defaults[1]) if defaults and defaults[1] is not None else -1
    inputs = []
    outputs = []
    for index, device in enumerate(devices):
        value = {"id": str(index), "name": _name(device["name"])}
        if int(device["max_input_channels"]) > 0:
            inputs.append(value)
        if int(device["max_output_channels"]) > 0:
            outputs.append(value)
    return {"inputs": inputs, "outputs": outputs, "default_input": str(input_default), "default_output": str(output_default)}


def resolve_device(value: str) -> int | str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return int(text) if text.isdigit() else text
