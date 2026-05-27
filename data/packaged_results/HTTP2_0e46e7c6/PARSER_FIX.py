import sys

# SETTINGS frame type constant
SETTINGS_FRAME_TYPE = 0x4

# SETTINGS identifiers
SETTINGS_HEADER_TABLE_SIZE = 0x1
SETTINGS_ENABLE_PUSH = 0x2
SETTINGS_MAX_CONCURRENT_STREAMS = 0x3
SETTINGS_INITIAL_WINDOW_SIZE = 0x4
SETTINGS_MAX_FRAME_SIZE = 0x5
SETTINGS_MAX_HEADER_LIST_SIZE = 0x6

def parse_packet_frame_header(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a Frame Header as described in RFC 7540 Section 4.1.
    """
    if len(remaining_input) < 9:
        raise ValueError("Frame header requires at least 9 bytes")
    length = int.from_bytes(remaining_input[0:3], byteorder="big")
    frame_type = remaining_input[3]
    flags = remaining_input[4]
    r_and_stream_id = int.from_bytes(remaining_input[5:9], byteorder="big")
    r = (r_and_stream_id & 0x80000000) >> 31
    stream_identifier = r_and_stream_id & 0x7FFFFFFF
    if length > 16384:
        pass
    if len(remaining_input) < 9 + length:
        raise ValueError("Not enough bytes for frame payload as specified by Length field")
    payload = remaining_input[9:9+length]
    remaining_bytes = remaining_input[9+length:]
    result = {
        "length": length,
        "type": frame_type,
        "flags": flags,
        "r": r,
        "stream_identifier": stream_identifier,
        "payload": payload,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_data_frame(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse an HTTP/2 DATA frame payload according to RFC 7540 Section 6.1.
    """
    flags = current_result.get("flags")
    if flags is None:
        raise ValueError("DATA frame requires 'flags' field in current_result")
    padded = bool(flags & 0x8)
    payload_length = current_result.get("length")
    if payload_length is None:
        raise ValueError("DATA frame requires 'length' field in current_result")
    if len(remaining_input) < payload_length:
        raise ValueError("Insufficient bytes for DATA frame payload")
    payload = remaining_input[:payload_length]
    remaining_bytes = remaining_input[payload_length:]
    pad_length = None
    data = b""
    padding = b""
    if padded:
        if len(payload) < 1:
            raise ValueError("DATA frame with PADDED flag set requires at least 1 byte for Pad Length")
        pad_length = payload[0]
        if pad_length > len(payload) - 1:
            raise ValueError("Pad Length exceeds available payload size (connection error: PROTOCOL_ERROR)")
        data = payload[1:len(payload)-pad_length] if pad_length > 0 else payload[1:]
        padding = payload[len(payload)-pad_length:] if pad_length > 0 else b""
    else:
        data = payload
        padding = b""
    if padding and any(b != 0 for b in padding):
        raise ValueError("Non-zero padding octets detected (connection error: PROTOCOL_ERROR)")
    result = {
        "pad_length": pad_length,
        "data": data,
        "padding": padding,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_headers_frame(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a HEADERS frame payload according to RFC 7540 Section 6.2.
    """
    if 'flags' not in current_result or 'length' not in current_result or 'stream_id' not in current_result:
        raise ValueError("current_result must contain 'flags', 'length', and 'stream_id'")
    flags = current_result['flags']
    length = current_result['length']
    stream_id = current_result['stream_id']
    if stream_id == 0:
        raise ValueError("HEADERS frame received with stream_id 0 (PROTOCOL_ERROR)")
    if len(remaining_input) < length:
        raise ValueError(f"HEADERS frame payload too short: expected {length}, got {len(remaining_input)}")
    payload = remaining_input[:length]
    remaining_bytes = remaining_input[length:]
    offset = 0
    result = {}
    padded = bool(flags & 0x8)
    priority = bool(flags & 0x20)
    pad_length = None
    if padded:
        if offset + 1 > len(payload):
            raise ValueError("Insufficient payload for Pad Length field")
        pad_length = payload[offset]
        offset += 1
        result['pad_length'] = pad_length
    else:
        result['pad_length'] = None
    if priority:
        if offset + 5 > len(payload):
            raise ValueError("Insufficient payload for Priority fields")
        e_and_stream_dep = int.from_bytes(payload[offset:offset+4], byteorder='big')
        exclusive = bool((e_and_stream_dep & 0x80000000) >> 31)
        stream_dependency = e_and_stream_dep & 0x7FFFFFFF
        weight = payload[offset+4]
        offset += 5
        result['exclusive'] = exclusive
        result['stream_dependency'] = stream_dependency
        result['weight'] = weight
    else:
        result['exclusive'] = None
        result['stream_dependency'] = None
        result['weight'] = None
    if padded:
        if pad_length > len(payload) - offset:
            raise ValueError("Padding length exceeds remaining payload (PROTOCOL_ERROR)")
        header_block_fragment = payload[offset:len(payload)-pad_length]
        padding = payload[len(payload)-pad_length:]
    else:
        header_block_fragment = payload[offset:]
        padding = b''
    result['header_block_fragment'] = header_block_fragment
    result['padding'] = padding
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_priority(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a PRIORITY frame (type=0x2) as specified in RFC 7540 Section 6.3.
    """
    # Enforce stream identifier is not zero
    if current_result.get("stream_identifier", 0) == 0:
        raise ValueError("PRIORITY frame received with stream identifier 0 (PROTOCOL_ERROR)")
    # Enforce payload length is exactly 5 bytes
    if len(remaining_input) != 5:
        raise ValueError("PRIORITY frame payload length must be exactly 5 bytes (FRAME_SIZE_ERROR)")
    first_byte = remaining_input[0]
    e_flag = (first_byte & 0x80) >> 7
    stream_dependency = ((first_byte & 0x7F) << 24) | (remaining_input[1] << 16) | (remaining_input[2] << 8) | remaining_input[3]
    weight = remaining_input[4]
    result = {
        "exclusive": bool(e_flag),
        "stream_dependency": stream_dependency,
        "weight": weight,
    }
    current_result.update(result)
    remaining_bytes = remaining_input[5:]
    return current_result, remaining_bytes

def parse_packet_rst_stream(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse an HTTP/2 RST_STREAM frame payload according to RFC 7540 Section 6.4.
    """
    if len(remaining_input) < 4:
        raise ValueError("RST_STREAM frame payload requires at least 4 bytes for Error Code")
    if len(remaining_input) > 4:
        raise ValueError("RST_STREAM frame payload must be exactly 4 bytes (FRAME_SIZE_ERROR)")
    error_code = int.from_bytes(remaining_input[:4], byteorder="big")
    remaining_bytes = remaining_input[4:]
    result = {
        "error_code": error_code
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_settings(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a SETTINGS frame (type=0x4) according to RFC 7540 Section 6.5.
    """
    if len(remaining_input) < 9:
        raise ValueError("SETTINGS frame requires at least 9 bytes for header")
    length = int.from_bytes(remaining_input[0:3], byteorder="big")
    frame_type = remaining_input[3]
    flags = remaining_input[4]
    stream_id = int.from_bytes(remaining_input[5:9], byteorder="big") & 0x7FFFFFFF
    if frame_type != SETTINGS_FRAME_TYPE:
        raise ValueError(f"Expected frame type 0x4 for SETTINGS, got 0x{frame_type:x}")
    if stream_id != 0:
        raise ValueError("SETTINGS frame must have stream identifier 0")
    ack_flag = bool(flags & 0x1)
    payload = remaining_input[9:9+length]
    remaining_bytes = remaining_input[9+length:]
    if ack_flag:
        if length != 0:
            raise ValueError("SETTINGS frame with ACK flag set must have zero length payload (FRAME_SIZE_ERROR)")
        settings = []
    else:
        if length % 6 != 0:
            raise ValueError("SETTINGS frame payload length must be a multiple of 6 (FRAME_SIZE_ERROR)")
        settings = []
        offset = 0
        while offset < length:
            if offset + 6 > len(payload):
                raise ValueError("Incomplete SETTINGS parameter in payload (PROTOCOL_ERROR)")
            identifier = int.from_bytes(payload[offset:offset+2], byteorder="big")
            value = int.from_bytes(payload[offset+2:offset+6], byteorder="big")
            if identifier == SETTINGS_HEADER_TABLE_SIZE:
                pass
            elif identifier == SETTINGS_ENABLE_PUSH:
                if value not in (0, 1):
                    raise ValueError("SETTINGS_ENABLE_PUSH value must be 0 or 1 (PROTOCOL_ERROR)")
            elif identifier == SETTINGS_MAX_CONCURRENT_STREAMS:
                pass
            elif identifier == SETTINGS_INITIAL_WINDOW_SIZE:
                if value > 0x7FFFFFFF:
                    raise ValueError("SETTINGS_INITIAL_WINDOW_SIZE value above 2^31-1 (FLOW_CONTROL_ERROR)")
            elif identifier == SETTINGS_MAX_FRAME_SIZE:
                if value < 16384 or value > 16777215:
                    raise ValueError("SETTINGS_MAX_FRAME_SIZE value out of range (PROTOCOL_ERROR)")
            elif identifier == SETTINGS_MAX_HEADER_LIST_SIZE:
                pass
            settings.append({"identifier": identifier, "value": value})
            offset += 6
    result = {
        "length": length,
        "type": frame_type,
        "flags": flags,
        "stream_id": stream_id,
        "ack": ack_flag,
        "settings": settings,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_push_promise(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a PUSH_PROMISE frame payload according to RFC 7540 Section 6.6.
    """
    if len(remaining_input) < 4:
        raise ValueError("PUSH_PROMISE frame requires at least 4 bytes for Promised Stream ID")
    padded = current_result.get("padded", False)
    end_headers = current_result.get("end_headers", False)
    offset = 0
    pad_length = None
    if padded:
        pad_length = remaining_input[0]
        offset += 1
    if len(remaining_input) < offset + 4:
        raise ValueError("Insufficient bytes for Promised Stream ID")
    promised_stream_id_bytes = remaining_input[offset:offset+4]
    promised_stream_id = int.from_bytes(promised_stream_id_bytes, byteorder="big") & 0x7FFFFFFF
    reserved_bit = (promised_stream_id_bytes[0] & 0x80) >> 7
    offset += 4
    if padded:
        if pad_length is None:
            raise ValueError("PADDED flag set but Pad Length field missing")
        if len(remaining_input) < offset + pad_length:
            raise ValueError("Insufficient bytes for padding")
        header_block_fragment = remaining_input[offset:len(remaining_input)-pad_length]
        padding = remaining_input[len(remaining_input)-pad_length:len(remaining_input)]
        remaining_bytes = remaining_input[len(remaining_input):]
    else:
        header_block_fragment = remaining_input[offset:]
        padding = b""
        remaining_bytes = b""
    result = {
        "pad_length": pad_length,
        "reserved_bit": reserved_bit,
        "promised_stream_id": promised_stream_id,
        "header_block_fragment": header_block_fragment,
        "padding": padding,
        "end_headers": end_headers,
        "padded": padded,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_ping_frame(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a PING frame (type=0x6) as specified in RFC.
    """
    # Check for non-zero stream identifier (RFC 7540: PING frames must have stream identifier 0)
    if current_result.get('stream_identifier', 0) != 0:
        raise ValueError('PING frame received with non-zero stream identifier (PROTOCOL_ERROR)')
    if len(remaining_input) < 8:
        raise ValueError("PING frame requires at least 8 bytes for opaque data")
    opaque_data = remaining_input[:8]
    remaining_bytes = remaining_input[8:]
    result = {
        "opaque_data": opaque_data
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_goaway(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a GOAWAY frame payload according to RFC 7540 Section 6.8.
    """
    # Check for non-zero stream identifier (RFC 7540: GOAWAY frames must have stream identifier 0)
    if current_result.get('stream_identifier', 0) != 0:
        raise ValueError('GOAWAY frame received with non-zero stream identifier (PROTOCOL_ERROR)')
    if len(remaining_input) < 8:
        raise ValueError("GOAWAY frame payload must be at least 8 bytes")
    last_stream_id_raw = int.from_bytes(remaining_input[0:4], byteorder="big")
    reserved = (last_stream_id_raw & 0x80000000) >> 31
    last_stream_id = last_stream_id_raw & 0x7FFFFFFF
    error_code = int.from_bytes(remaining_input[4:8], byteorder="big")
    debug_data = remaining_input[8:]
    remaining_bytes = b""
    result = {
        "reserved": reserved,
        "last_stream_id": last_stream_id,
        "error_code": error_code,
        "debug_data": debug_data,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_window_update(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a WINDOW_UPDATE frame (type=0x8) from RFC 7540 Section 6.9.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # WINDOW_UPDATE payload must be exactly 4 bytes
    if len(remaining_input) < 4:
        raise ValueError("WINDOW_UPDATE frame payload requires at least 4 bytes")
    payload = remaining_input[:4]
    remaining_bytes = remaining_input[4:]

    # Parse the reserved bit and window size increment
    reserved = (payload[0] & 0x80) >> 7  # Highest bit of first byte
    window_size_increment = ((payload[0] & 0x7F) << 24) | (payload[1] << 16) | (payload[2] << 8) | payload[3]

    # Validate window size increment (must be 1..2^31-1)
    if window_size_increment == 0:
        raise ValueError("WINDOW_UPDATE frame with window_size_increment=0 is a protocol error")
    if window_size_increment > 0x7FFFFFFF:
        raise ValueError("WINDOW_UPDATE frame window_size_increment exceeds 31 bits")

    result = {
        "reserved": reserved,
        "window_size_increment": window_size_increment,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_continuation_frame(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a CONTINUATION frame (type=0x9) as specified in RFC 7540 Section 6.10.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # CONTINUATION frame header is 9 bytes (HTTP/2 frame header)
    if len(remaining_input) < 9:
        raise ValueError("CONTINUATION frame requires at least 9 bytes for frame header")

    # Parse HTTP/2 frame header
    length = int.from_bytes(remaining_input[0:3], byteorder="big")  # 24 bits
    frame_type = remaining_input[3]
    flags = remaining_input[4]
    reserved_and_stream_id = int.from_bytes(remaining_input[5:9], byteorder="big")
    stream_id = reserved_and_stream_id & 0x7FFFFFFF  # 31 bits, ignore reserved bit

    # Validate frame type
    if frame_type != 0x9:
        raise ValueError(f"Expected CONTINUATION frame type 0x9, got 0x{frame_type:02x}")

    # CONTINUATION frames MUST be associated with a stream (stream_id != 0)
    if stream_id == 0:
        raise ValueError("CONTINUATION frame received with stream identifier 0x0 (PROTOCOL_ERROR)")

    # Check that the payload is present
    if len(remaining_input) < 9 + length:
        raise ValueError("Not enough bytes for CONTINUATION frame payload")

    # Parse payload: header block fragment
    header_block_fragment = remaining_input[9:9+length]
    remaining_bytes = remaining_input[9+length:]

    # Parse flags
    end_headers = bool(flags & 0x4)  # END_HEADERS is bit 2

    result = {
        "length": length,
        "type": frame_type,
        "flags": flags,
        "stream_id": stream_id,
        "end_headers": end_headers,
        "header_block_fragment": header_block_fragment,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def main():
    try:
        if len(sys.argv) < 2:
            print("Usage: python script.py <binary_file>")
            sys.exit(1)
        with open(sys.argv[1], "rb") as f:
            data = f.read()
        current_result, remaining = parse_packet_frame_header({}, data)
        frame_type = current_result.get("type")
        if frame_type == 0x0:  # DATA frame
            if current_result.get("stream_identifier", 0) == 0:
                raise ValueError("DATA frame received with stream identifier 0 (connection error: PROTOCOL_ERROR)")
            current_result, remaining = parse_packet_data_frame(current_result, current_result["payload"])
        elif frame_type == 0x1:  # HEADERS frame
            current_result['stream_id'] = current_result.get('stream_identifier')
            current_result, remaining = parse_packet_headers_frame(current_result, current_result["payload"])
        elif frame_type == 0x2:  # PRIORITY frame
            current_result, remaining = parse_packet_priority(current_result, current_result["payload"])
        elif frame_type == 0x3:  # RST_STREAM frame
            current_result, remaining = parse_packet_rst_stream(current_result, current_result["payload"])
        elif frame_type == 0x4:  # SETTINGS frame
            current_result, remaining = parse_packet_settings({}, data)
        elif frame_type == 0x5:  # PUSH_PROMISE frame
            flags = current_result.get("flags", 0)
            padded = bool(flags & 0x8)
            end_headers = bool(flags & 0x4)
            current_result["padded"] = padded
            current_result["end_headers"] = end_headers
            current_result, remaining = parse_packet_push_promise(current_result, current_result["payload"])
        elif frame_type == 0x6:  # PING frame
            current_result, remaining = parse_packet_ping_frame(current_result, current_result["payload"])
        elif frame_type == 0x7:  # GOAWAY frame
            current_result, remaining = parse_packet_goaway(current_result, current_result["payload"])
        elif frame_type == 0x8:  # WINDOW_UPDATE frame
            current_result, remaining = parse_packet_window_update(current_result, current_result["payload"])
        elif frame_type == 0x9:  # CONTINUATION frame
            current_result, remaining = parse_packet_continuation_frame(current_result, data)
        print(current_result)
    except Exception as e:
        print(str(e))
        if 'current_result' in locals():
            print(current_result)
        sys.exit(1)

if __name__ == "__main__":
    main()
