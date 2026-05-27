import sys

def parse_packet_ntp_extension_field(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse an NTP Extension Field as described in RFC 5905 section 7.5.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # Minimum field length is 16 bytes (4 words)
    if len(remaining_input) < 4:
        raise ValueError("NTP Extension Field requires at least 4 bytes for header")

    # Parse Field Type (2 bytes) and Length (2 bytes)
    field_type = int.from_bytes(remaining_input[0:2], byteorder="big")
    length = int.from_bytes(remaining_input[2:4], byteorder="big")

    # Validate minimum length
    if length < 16:
        raise ValueError(f"NTP Extension Field length {length} is less than minimum 16 bytes")
    if length > len(remaining_input):
        raise ValueError(f"NTP Extension Field length {length} exceeds available input bytes {len(remaining_input)}")
    if length % 4 != 0:
        raise ValueError(f"NTP Extension Field length {length} is not a multiple of 4 (word aligned)")

    # Value field is everything after header up to (length - 4) bytes
    value = remaining_input[4:length]

    # Padding is any trailing zero bytes to align to 4 bytes (already included in length)
    # No need to parse padding separately, but we can check if the last bytes are zero
    padding_length = length - (4 + len(value))
    if padding_length > 0:
        padding = remaining_input[length - padding_length:length]
        if any(b != 0 for b in padding):
            raise ValueError("NTP Extension Field padding must be zero")
    else:
        padding = b""

    # Prepare result
    result = {
        "field_type": field_type,
        "length": length,
        "value": value,
        "padding": padding,
    }
    current_result.update(result)
    remaining_bytes = remaining_input[length:]
    return current_result, remaining_bytes

def parse_packet_ntp_header(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse an NTPv4 packet header, extension fields, and optional MAC as per RFC 5905.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # The NTP header is 48 bytes (12 words of 4 bytes each)
    if len(remaining_input) < 48:
        raise ValueError("NTP packet header requires at least 48 bytes")

    # Parse first word (4 bytes)
    first_word = remaining_input[0]
    leap = (first_word & 0xC0) >> 6  # 2 bits
    version = (first_word & 0x38) >> 3  # 3 bits
    mode = first_word & 0x07  # 3 bits
    stratum = remaining_input[1]
    poll = int.from_bytes(remaining_input[2:3], byteorder="big", signed=True)
    precision = int.from_bytes(remaining_input[3:4], byteorder="big", signed=True)

    # Validate leap, version, mode, stratum
    if leap > 3:
        raise ValueError(f"Leap Indicator value {leap} is invalid (must be 0-3)")
    if version < 1 or version > 7:
        raise ValueError(f"Version {version} is invalid (must be 1-7)")
    if mode > 7:
        raise ValueError(f"Mode {mode} is invalid (must be 0-7)")
    if stratum > 255:
        raise ValueError(f"Stratum {stratum} is invalid (must be 0-255)")

    # Parse root delay and root dispersion (NTP short format: 16.16 fixed point)
    rootdelay = int.from_bytes(remaining_input[4:8], byteorder="big", signed=True)
    rootdisp = int.from_bytes(remaining_input[8:12], byteorder="big", signed=True)

    # Parse reference ID (4 bytes)
    refid = remaining_input[12:16]

    # KoD validation: If stratum is 0, refid must be 4 printable ASCII chars, left-justified, zero-filled
    if stratum == 0:
        if refid == b"\x00\x00\x00\x00":
            raise ValueError("KoD packet must not have all-zero refid")
        if any(b < 0x20 or b > 0x7E for b in refid.rstrip(b"\x00")):
            raise ValueError("KoD kiss code must consist of printable ASCII characters (0x20–0x7E)")

    # Stratum-1 reference clock ID must be printable ASCII and not all-zero
    if stratum == 1:
        if refid == b"\x00\x00\x00\x00":
            raise ValueError("Stratum-1 packet must not have an all-zero Reference ID")
        if any(b < 0x20 or b > 0x7E for b in refid.rstrip(b"\x00")):
            raise ValueError("Stratum-1 Reference ID must be printable ASCII (0x20–0x7E)")

    # Parse timestamps (8 bytes each, 64 bits)
    reftime = remaining_input[16:24]
    org = remaining_input[24:32]
    rec = remaining_input[32:40]
    xmt = remaining_input[40:48]

    # Prepare result
    result = {
        "leap": leap,
        "version": version,
        "mode": mode,
        "stratum": stratum,
        "poll": poll,
        "precision": precision,
        "rootdelay": rootdelay,
        "rootdisp": rootdisp,
        "refid": refid,
        "reftime": reftime,
        "org": org,
        "rec": rec,
        "xmt": xmt,
    }

    # Move past header
    offset = 48
    extension_fields = []
    # Extension fields are present if there are at least 16 bytes left before the MAC
    # MAC is 20 bytes (4 for keyid, 16 for digest) if present
    # If there are no extension fields, next 20 bytes (if present) is MAC
    # If there are extension fields, they are always a multiple of 4 bytes, and each has a 2-byte length field
    # Parse extension fields until less than 20 bytes remain
    while len(remaining_input) - offset >= 16:
        # Check if enough bytes for an extension field header
        if len(remaining_input) - offset < 4:
            break
        # Peek at extension field length
        ext_len = int.from_bytes(remaining_input[offset+2:offset+4], byteorder="big")
        if ext_len < 16 or ext_len % 4 != 0:
            raise ValueError(f"Invalid extension field length {ext_len} at offset {offset}")
        if len(remaining_input) - offset < ext_len:
            break  # Not enough bytes for this extension field
        ext_field, _ = parse_packet_ntp_extension_field({}, remaining_input[offset:offset+ext_len])
        extension_fields.append(ext_field)
        offset += ext_len
    result["extension_fields"] = extension_fields

    # Check for MAC (Key Identifier + Digest)
    mac = None
    if len(remaining_input) - offset >= 20:
        keyid = int.from_bytes(remaining_input[offset:offset+4], byteorder="big")
        dgst = remaining_input[offset+4:offset+20]
        mac = {"keyid": keyid, "dgst": dgst}
        offset += 20
    result["mac"] = mac

    # Update current_result
    current_result.update(result)
    return current_result, remaining_input[offset:]

def parse_packet_kiss_o_death_packet(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a Kiss-o'-Death (KoD) NTP packet as described in RFC 5905 section 7.4.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # NTP packet is 48 bytes (without extensions/auth)
    if len(remaining_input) < 48:
        raise ValueError("NTP packet must be at least 48 bytes for KoD packet")

    # Parse the first byte: LI (2 bits), VN (3 bits), Mode (3 bits)
    first_byte = remaining_input[0]
    li = (first_byte & 0xC0) >> 6  # Leap Indicator
    vn = (first_byte & 0x38) >> 3  # Version Number
    mode = first_byte & 0x07       # Mode

    stratum = remaining_input[1]
    poll = remaining_input[2]
    precision = remaining_input[3]

    root_delay = int.from_bytes(remaining_input[4:8], byteorder="big", signed=True)
    root_dispersion = int.from_bytes(remaining_input[8:12], byteorder="big", signed=True)
    reference_id = remaining_input[12:16]

    # KoD packets must have stratum 0
    if stratum != 0:
        raise ValueError(f"Stratum must be 0 for KoD packet, got {stratum}")

    # Kiss code is a 4-byte ASCII string, left-justified, zero-filled
    if reference_id == b"\x00\x00\x00\x00":
        raise ValueError("KoD packet must carry a 4-char ASCII kiss code, not all-zero refid")
    try:
        kiss_code = reference_id.decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("Reference Identifier is not valid ASCII for KoD packet")
    if any(c < 0x20 or c > 0x7E for c in reference_id.rstrip(b"\x00")):
        raise ValueError("Kiss code must consist of printable ASCII characters")
    if len(kiss_code.rstrip("\0")) == 0:
        raise ValueError("Kiss code may not be empty")

    # The rest of the fields are present but timestamps are undefined and must be discarded
    # (Reference Timestamp, Originate Timestamp, Receive Timestamp, Transmit Timestamp)
    reference_timestamp = remaining_input[16:24]
    originate_timestamp = remaining_input[24:32]
    receive_timestamp = remaining_input[32:40]
    transmit_timestamp = remaining_input[40:48]

    # Build result dictionary
    result = {
        "leap_indicator": li,
        "version": vn,
        "mode": mode,
        "stratum": stratum,
        "poll": poll,
        "precision": precision,
        "root_delay": root_delay,
        "root_dispersion": root_dispersion,
        "reference_id": reference_id,
        "kiss_code": kiss_code,
        "reference_timestamp": reference_timestamp,
        "originate_timestamp": originate_timestamp,
        "receive_timestamp": receive_timestamp,
        "transmit_timestamp": transmit_timestamp,
    }

    # Update current_result with parsed fields
    current_result.update(result)

    # Return the parsed result and any remaining bytes (after 48 bytes)
    return current_result, remaining_input[48:]

def main():
    import sys
    try:
        if len(sys.argv) < 2:
            print("Usage: python script.py <filename>")
            sys.exit(1)
        with open(sys.argv[1], "rb") as f:
            data = f.read()
        # Try KoD first, if fails, fallback to generic NTP header
        try:
            result, _ = parse_packet_kiss_o_death_packet({}, data)
        except Exception:
            result, _ = parse_packet_ntp_header({}, data)
        print(result)
    except Exception as e:
        print(str(e))
        if 'result' in locals():
            print(result)
        sys.exit(1)

if __name__ == "__main__":
    main()
