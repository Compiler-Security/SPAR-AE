import sys

def parse_packet_sctp_common_header(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse the SCTP Common Header from RFC 4960 Section 3.1.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # The SCTP common header is 12 bytes
    if len(remaining_input) < 12:
        raise ValueError("SCTP Common Header requires at least 12 bytes")

    source_port = int.from_bytes(remaining_input[0:2], byteorder="big")
    dest_port = int.from_bytes(remaining_input[2:4], byteorder="big")
    verification_tag = int.from_bytes(remaining_input[4:8], byteorder="big")
    checksum = int.from_bytes(remaining_input[8:12], byteorder="big")

    # Port numbers must not be zero
    if source_port == 0:
        raise ValueError("Source Port Number must not be zero")
    if dest_port == 0:
        raise ValueError("Destination Port Number must not be zero")

    result = {
        "source_port": source_port,
        "destination_port": dest_port,
        "verification_tag": verification_tag,
        "checksum": checksum,
    }
    current_result.update(result)
    return current_result, remaining_input[12:]


def parse_packet_sctp_chunk(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a generic SCTP chunk (RFC 4960 Section 3.2).

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # Minimum chunk header is 4 bytes
    if len(remaining_input) < 4:
        raise ValueError("SCTP chunk requires at least 4 bytes for header")

    chunk_type = remaining_input[0]
    chunk_flags = remaining_input[1]
    chunk_length = int.from_bytes(remaining_input[2:4], byteorder="big")

    # Chunk Length must be at least 4 (header only)
    if chunk_length < 4:
        raise ValueError(f"Chunk Length {chunk_length} is less than minimum 4 bytes")
    if chunk_length > len(remaining_input):
        raise ValueError(f"Chunk Length {chunk_length} exceeds available input {len(remaining_input)}")

    chunk_value = remaining_input[4:chunk_length]
    # Chunks are padded to 4-byte boundary, but padding is not included in chunk_length
    total_chunk_len = (chunk_length + 3) & ~0x03
    remaining_bytes = remaining_input[total_chunk_len:]

    result = {
        "chunk_type": chunk_type,
        "chunk_flags": chunk_flags,
        "chunk_length": chunk_length,
        "chunk_value": chunk_value,
    }
    current_result.update(result)
    return current_result, remaining_bytes


def parse_packet_sctp_packet(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse an SCTP packet (RFC 4960 Section 3).

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # Parse the common header
    header_result, remaining = parse_packet_sctp_common_header({}, remaining_input)
    chunks = []
    # Parse all chunks until no more data
    while len(remaining) >= 4:
        chunk_result, remaining = parse_packet_sctp_chunk({}, remaining)
        chunks.append(chunk_result)
    result = {
        "common_header": header_result,
        "chunks": chunks,
    }
    current_result.update(result)
    return current_result, remaining


def main():
    import sys
    import traceback
    parsed_result = {}
    try:
        if len(sys.argv) < 2:
            print("Usage: python script.py <input_file>")
            sys.exit(1)
        with open(sys.argv[1], "rb") as f:
            data = f.read()
        parsed_result, remaining = parse_packet_sctp_packet({}, data)
        if remaining:
            print(f"Warning: {len(remaining)} bytes left unparsed.")
        print(parsed_result)
    except Exception as e:
        print(str(e))
        print(parsed_result)
        sys.exit(1)

if __name__ == "__main__":
    main()
