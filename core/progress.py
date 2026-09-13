import re


PROGRESS_PATTERN = re.compile(r"(?<!\d)(100|[1-9]?\d)%")


def extract_progress(text):
    """Return the last 7-Zip percentage found in a progress message."""

    matches = PROGRESS_PATTERN.findall(text)

    if not matches:
        return None

    return int(matches[-1])


def iter_output_messages(stream):
    """Yield messages separated by either carriage returns or newlines."""

    buffer = bytearray()

    while True:
        character = stream.read(1)

        if not character:
            break

        if character in (b"\r", b"\n"):
            if buffer:
                yield buffer.decode("utf-8", errors="replace")
                buffer.clear()
        else:
            buffer.extend(character)

    if buffer:
        yield buffer.decode("utf-8", errors="replace")
