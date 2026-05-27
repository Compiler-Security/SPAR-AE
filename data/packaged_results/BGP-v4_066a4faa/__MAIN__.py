def parse_packet_message_header(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a Message Header as specified in RFC section 4.1.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # The header is 19 bytes: Marker (16) + Length (2) + Type (1)
    if len(remaining_input) < 19:
        raise ValueError("Message Header requires at least 19 bytes")

    # Parse Marker field (16 bytes)
    marker = remaining_input[:16]
    if marker != b'\xff' * 16:
        raise ValueError("Marker field must be all ones (0xff)")

    # Parse Length field (2 bytes, unsigned integer, big endian)
    length = int.from_bytes(remaining_input[16:18], byteorder="big")
    if length < 19 or length > 4096:
        raise ValueError(f"Length field {length} out of valid range (19-4096)")
    if length > len(remaining_input):
        raise ValueError(f"Length field {length} exceeds available input length {len(remaining_input)}")

    # Parse Type field (1 byte)
    type_code = remaining_input[18]
    if type_code not in (1, 2, 3, 4, 5):
        raise ValueError(f"Unknown message type code {type_code}")

    # Prepare result dictionary
    result = {
        "marker": marker,
        "length": length,
        "type": type_code,
    }
    current_result.update(result)

    # Remaining bytes after header
    remaining_bytes = remaining_input[19:length]

    return current_result, remaining_bytes

def parse_packet_bgp_open_message(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a BGP OPEN message according to RFC 4271 section 4.2.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # The minimum length of the OPEN message body (excluding the 19-byte BGP header) is 10 bytes
    if len(remaining_input) < 10:
        raise ValueError("BGP OPEN message body requires at least 10 bytes")

    # Parse fixed fields
    version = remaining_input[0]
    my_autonomous_system = int.from_bytes(remaining_input[1:3], byteorder="big")
    hold_time = int.from_bytes(remaining_input[3:5], byteorder="big")
    bgp_identifier = int.from_bytes(remaining_input[5:9], byteorder="big")
    opt_param_len = remaining_input[9]

    # Validate Version
    if version != 4:
        raise ValueError(f"BGP Version must be 4, got {version}")

    # Validate Hold Time (must be 0 or >= 3)
    if hold_time != 0 and hold_time < 3:
        raise ValueError(f"Hold Time must be 0 or >= 3, got {hold_time}")

    # Validate BGP Identifier (must be nonzero)
    if bgp_identifier == 0:
        raise ValueError("BGP Identifier must be nonzero")

    # Check if enough bytes for optional parameters
    if len(remaining_input) < 10 + opt_param_len:
        raise ValueError("Not enough bytes for Optional Parameters")

    # Parse Optional Parameters
    optional_parameters = []
    opt_params_bytes = remaining_input[10:10 + opt_param_len]
    opt_params_offset = 0
    while opt_params_offset < len(opt_params_bytes):
        if len(opt_params_bytes) - opt_params_offset < 2:
            raise ValueError("Optional Parameter too short for Type and Length")
        param_type = opt_params_bytes[opt_params_offset]
        param_length = opt_params_bytes[opt_params_offset + 1]
        if len(opt_params_bytes) - opt_params_offset - 2 < param_length:
            raise ValueError("Optional Parameter Value length exceeds available bytes")
        param_value = opt_params_bytes[opt_params_offset + 2: opt_params_offset + 2 + param_length]
        # Use a placeholder for parameter value parsing
        param_result, _ = parse_packet_bgp_optional_parameter({
            "type": param_type,
            "length": param_length,
            "value": param_value
        }, param_value)
        optional_parameters.append(param_result)
        opt_params_offset += 2 + param_length

    # Remaining bytes after the OPEN message
    remaining_bytes = remaining_input[10 + opt_param_len:]

    result = {
        "version": version,
        "my_autonomous_system": my_autonomous_system,
        "hold_time": hold_time,
        "bgp_identifier": bgp_identifier,
        "optional_parameters_length": opt_param_len,
        "optional_parameters": optional_parameters
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_bgp_optional_parameter(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Placeholder for parsing a BGP Optional Parameter.
    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse
    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)
    """
    # For now, just return the current_result and empty bytes (since we already extracted the value)
    return current_result, b""

def parse_packet_bgp_update_message(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a BGP UPDATE message according to RFC 4271 section 4.3.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # The minimum length of the UPDATE message is 23 octets (excluding the fixed BGP header)
    if len(remaining_input) < 4:
        raise ValueError("BGP UPDATE message requires at least 4 bytes for Withdrawn Routes Length and Total Path Attribute Length fields")

    # Parse Withdrawn Routes Length (2 octets)
    withdrawn_routes_length = int.from_bytes(remaining_input[0:2], byteorder="big")
    if len(remaining_input) < 2 + withdrawn_routes_length + 2:
        raise ValueError("Insufficient bytes for Withdrawn Routes field")

    # Parse Withdrawn Routes (variable)
    withdrawn_routes = []
    withdrawn_routes_data = remaining_input[2:2 + withdrawn_routes_length]
    idx = 0
    while idx < withdrawn_routes_length:
        if idx >= len(withdrawn_routes_data):
            raise ValueError("Malformed Withdrawn Routes field")
        prefix_length = withdrawn_routes_data[idx]
        idx += 1
        # Insert prefix length check for IPv4
        if prefix_length > 32:
            raise ValueError(f"Prefix length {prefix_length} exceeds maximum 32 bits for IPv4")
        prefix_bytes = (prefix_length + 7) // 8
        if idx + prefix_bytes > len(withdrawn_routes_data):
            raise ValueError("Withdrawn route prefix overruns field length")
        prefix = withdrawn_routes_data[idx:idx + prefix_bytes]
        withdrawn_routes.append({
            "length": prefix_length,
            "prefix": prefix
        })
        idx += prefix_bytes

    # Parse Total Path Attribute Length (2 octets)
    tpal_offset = 2 + withdrawn_routes_length
    if len(remaining_input) < tpal_offset + 2:
        raise ValueError("Insufficient bytes for Total Path Attribute Length field")
    total_path_attribute_length = int.from_bytes(remaining_input[tpal_offset:tpal_offset + 2], byteorder="big")

    # Parse Path Attributes (variable)
    path_attributes = []
    path_attr_offset = tpal_offset + 2
    if len(remaining_input) < path_attr_offset + total_path_attribute_length:
        raise ValueError("Insufficient bytes for Path Attributes field")
    path_attributes_data = remaining_input[path_attr_offset:path_attr_offset + total_path_attribute_length]
    idx = 0
    while idx < total_path_attribute_length:
        if idx + 2 > len(path_attributes_data):
            raise ValueError("Malformed Path Attribute header")
        attr_flags = path_attributes_data[idx]
        attr_type_code = path_attributes_data[idx + 1]
        ext_len = (attr_flags & 0x10) != 0
        if ext_len:
            if idx + 4 > len(path_attributes_data):
                raise ValueError("Malformed Path Attribute with extended length")
            attr_len = int.from_bytes(path_attributes_data[idx + 2:idx + 4], byteorder="big")
            attr_value_offset = idx + 4
            next_idx = attr_value_offset + attr_len
        else:
            if idx + 3 > len(path_attributes_data):
                raise ValueError("Malformed Path Attribute with normal length")
            attr_len = path_attributes_data[idx + 2]
            attr_value_offset = idx + 3
            next_idx = attr_value_offset + attr_len
        if next_idx > len(path_attributes_data):
            raise ValueError("Path Attribute value overruns field length")
        attr_value = path_attributes_data[attr_value_offset:next_idx]
        # Attribute-specific validation for well-known attributes
        if attr_type_code == 1:  # ORIGIN
            # ORIGIN must be length 1 and value 0,1,2
            if attr_len != 1 or attr_value[0] not in (0, 1, 2):
                raise ValueError(f"Invalid ORIGIN attribute value {attr_value[0]} (must be 0,1,2)")
        if attr_type_code == 2:  # AS_PATH
            # Validate AS_PATH segments: each segment type must be 1 or 2
            idx_seg = 0
            while idx_seg < attr_len:
                if idx_seg >= len(attr_value):
                    raise ValueError("Malformed AS_PATH segment header")
                seg_type = attr_value[idx_seg]
                if seg_type not in (1, 2):
                    raise ValueError(f"Invalid AS_PATH segment type {seg_type}")
                if idx_seg + 2 > attr_len:
                    raise ValueError("Malformed AS_PATH segment header")
                seg_len = attr_value[idx_seg + 1]
                idx_seg += 2 + seg_len * 2  # each AS number is 2 octets
            if idx_seg != attr_len:
                raise ValueError("AS_PATH attribute length mismatch")
        if attr_type_code == 7:  # AGGREGATOR
            # AGGREGATOR attribute must be exactly 6 bytes
            if attr_len != 6:
                raise ValueError(f"Invalid AGGREGATOR attribute length {attr_len} (must be 6)")
        # Add similar checks for other well-known attributes as required
        path_attributes.append({
            "flags": attr_flags,
            "type_code": attr_type_code,
            "length": attr_len,
            "value": attr_value
        })
        idx = next_idx

    # Parse Network Layer Reachability Information (NLRI)
    nlri_offset = path_attr_offset + total_path_attribute_length
    nlri_data = remaining_input[nlri_offset:]
    nlri = []
    idx = 0
    while idx < len(nlri_data):
        prefix_start = idx
        if idx >= len(nlri_data):
            break
        prefix_length = nlri_data[idx]
        idx += 1
        # Insert prefix length check for IPv4
        if prefix_length > 32:
            raise ValueError(f"Prefix length {prefix_length} exceeds maximum 32 bits for IPv4")
        prefix_bytes = (prefix_length + 7) // 8
        if idx + prefix_bytes > len(nlri_data):
            raise ValueError("NLRI prefix overruns field length")
        prefix = nlri_data[idx:idx + prefix_bytes]
        nlri.append({
            "length": prefix_length,
            "prefix": prefix
        })
        idx += prefix_bytes

    # Build result dictionary
    result = {
        "withdrawn_routes_length": withdrawn_routes_length,
        "withdrawn_routes": withdrawn_routes,
        "total_path_attribute_length": total_path_attribute_length,
        "path_attributes": path_attributes,
        "nlri": nlri
    }
    current_result.update(result)
    # All bytes are consumed in the BGP UPDATE message
    remaining_bytes = b""
    return current_result, remaining_bytes

def parse_packet_bgp_keepalive_message(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a BGP KEEPALIVE message according to RFC 4271 section 4.4.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # BGP KEEPALIVE message is exactly 19 bytes (header only)
    if len(remaining_input) < 19:
        raise ValueError("BGP KEEPALIVE message requires exactly 19 bytes")

    # Parse header fields
    marker = remaining_input[:16]
    length = int.from_bytes(remaining_input[16:18], byteorder="big")
    msg_type = remaining_input[18]

    # Validate marker field (should be all ones)
    if marker != b"\xff" * 16:
        raise ValueError("BGP message marker field must be all ones (0xff)")

    # Validate length field
    if length != 19:
        raise ValueError(f"BGP KEEPALIVE message length field must be 19, got {length}")

    # Validate message type (KEEPALIVE = 4)
    if msg_type != 4:
        raise ValueError(f"BGP KEEPALIVE message type must be 4, got {msg_type}")

    # Build result dictionary
    result = {
        "marker": marker,
        "length": length,
        "type": msg_type
    }

    # Update current_result with parsed fields
    current_result.update(result)

    # Remaining bytes after the KEEPALIVE message
    remaining_bytes = remaining_input[19:]

    return current_result, remaining_bytes

def parse_packet_notification_message(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a BGP NOTIFICATION message as per RFC 4271 section 4.5.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse (should start at NOTIFICATION message body)

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # The NOTIFICATION message body must be at least 2 bytes (Error Code + Error Subcode)
    if len(remaining_input) < 2:
        raise ValueError("NOTIFICATION message requires at least 2 bytes for Error Code and Error Subcode")

    error_code = remaining_input[0]
    error_subcode = remaining_input[1]
    data = remaining_input[2:]
    remaining_bytes = b""

    # Validate Error Code (must be 1-6 as per RFC, but allow others for extensibility)
    if error_code == 0:
        raise ValueError("Error Code 0 is not valid for NOTIFICATION message")

    # Validate Error Subcode (must be 0 or greater)
    if error_subcode < 0:
        raise ValueError("Error Subcode must be >= 0")

    # Per-Error-Code valid subcode checks
    valid_subcodes = {
        1: {1, 2, 3},                     # Message Header Error
        2: {1, 2, 3, 4, 6},               # OPEN Message Error
        3: {1, 2, 3, 4, 5, 6, 8, 9, 10, 11}, # UPDATE Message Error
        4: {0},                           # Hold Timer Expired
        5: {0},                           # Finite State Machine Error
        6: {0},                           # Cease
    }
    if error_code in valid_subcodes and error_subcode not in valid_subcodes[error_code]:
        raise ValueError(
            f"Invalid Error Subcode {error_subcode} for Error Code {error_code}")

    # Build result dictionary
    result = {
        "error_code": error_code,
        "error_subcode": error_subcode,
        "data": data,
    }

    # Update current_result with parsed fields
    current_result.update(result)

    return current_result, remaining_bytes

def main():
    import sys
    try:
        if len(sys.argv) < 2:
            print("Usage: python script.py <input_file>")
            sys.exit(1)
        with open(sys.argv[1], "rb") as f:
            data = f.read()
        # Parse the BGP message header first
        result, remaining = parse_packet_message_header({}, data)
        # If the type is 1 (OPEN), parse the OPEN message body
        if result.get("type") == 1:
            open_result, open_remaining = parse_packet_bgp_open_message({}, remaining)
            result["open_message"] = open_result
        # If the type is 2 (UPDATE), parse the UPDATE message body
        elif result.get("type") == 2:
            update_result, update_remaining = parse_packet_bgp_update_message({}, remaining)
            result["update_message"] = update_result
        # If the type is 3 (NOTIFICATION), parse the NOTIFICATION message body
        elif result.get("type") == 3:
            notification_result, notification_remaining = parse_packet_notification_message({}, remaining)
            result["notification_message"] = notification_result
        # If the type is 4 (KEEPALIVE), parse the KEEPALIVE message
        elif result.get("type") == 4:
            keepalive_result, keepalive_remaining = parse_packet_bgp_keepalive_message({}, data)
            result["keepalive_message"] = keepalive_result
        print(result)
    except Exception as e:
        print(str(e))
        import traceback
        traceback.print_exc()
        if 'result' in locals():
            print(result)
        sys.exit(1)

if __name__ == "__main__":
    main()
