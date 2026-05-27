def parse_packet_dns_header(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a DNS Header section from RFC 1035 section 4.1.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # DNS header is always 12 bytes
    if len(remaining_input) < 12:
        raise ValueError("DNS header requires at least 12 bytes")

    # Parse ID (16 bits)
    id_ = int.from_bytes(remaining_input[0:2], byteorder="big")

    # Parse flags and codes (16 bits)
    flags = int.from_bytes(remaining_input[2:4], byteorder="big")
    qr = (flags & 0x8000) >> 15
    opcode = (flags & 0x7800) >> 11
    aa = (flags & 0x0400) >> 10
    tc = (flags & 0x0200) >> 9
    rd = (flags & 0x0100) >> 8
    ra = (flags & 0x0080) >> 7
    z = (flags & 0x0070) >> 4
    rcode = flags & 0x000F

    # Validate Z field (must be zero)
    if z != 0:
        raise ValueError(f"Reserved Z field must be zero, got {z}")

    # Validate OPCODE (0-2 valid, 3-15 reserved – reject)
    if opcode > 2 and opcode < 16:
        raise ValueError(f"Reserved OPCODE value {opcode} is not allowed")
    elif opcode > 15:
        raise ValueError(f"Invalid OPCODE value {opcode}")

    # RFC: only 0-5 allowed – 6-15 reserved
    if rcode > 5:
        raise ValueError(f"Reserved/invalid RCODE value {rcode} is not allowed")

    # Parse QDCOUNT, ANCOUNT, NSCOUNT, ARCOUNT (16 bits each)
    qdcount = int.from_bytes(remaining_input[4:6], byteorder="big")
    ancount = int.from_bytes(remaining_input[6:8], byteorder="big")
    nscount = int.from_bytes(remaining_input[8:10], byteorder="big")
    arcount = int.from_bytes(remaining_input[10:12], byteorder="big")

    result = {
        "id": id_,
        "qr": qr,
        "opcode": opcode,
        "aa": aa,
        "tc": tc,
        "rd": rd,
        "ra": ra,
        "z": z,
        "rcode": rcode,
        "qdcount": qdcount,
        "ancount": ancount,
        "nscount": nscount,
        "arcount": arcount,
    }
    current_result.update(result)
    return current_result, remaining_input[12:]

def parse_packet_question_section(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a DNS Question Section as specified in RFC 1035 4.1.2.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # Parse QNAME: sequence of labels, each label is length octet + label bytes, terminated by zero length octet
    labels = []
    idx = 0
    while True:
        if idx >= len(remaining_input):
            raise ValueError("Insufficient bytes for QNAME label length octet")
        label_len = remaining_input[idx]
        idx += 1
        if label_len == 0:
            # End of QNAME
            break
        if idx + label_len > len(remaining_input):
            raise ValueError("Insufficient bytes for QNAME label data")
        label = remaining_input[idx:idx+label_len]
        labels.append(label)
        idx += label_len
    qname = b'.'.join(labels)
    # After QNAME, next 2 bytes: QTYPE
    if idx + 4 > len(remaining_input):
        raise ValueError("Insufficient bytes for QTYPE and QCLASS")
    qtype = int.from_bytes(remaining_input[idx:idx+2], byteorder="big")
    qclass = int.from_bytes(remaining_input[idx+2:idx+4], byteorder="big")
    idx += 4
    result = {
        "qname": qname,
        "labels": labels,
        "qtype": qtype,
        "qclass": qclass,
    }
    current_result.update(result)
    remaining_bytes = remaining_input[idx:]
    return current_result, remaining_bytes

def parse_packet_domain_name(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    labels = []
    idx = 0
    while True:
        if idx >= len(remaining_input):
            raise ValueError("Incomplete domain name in domain name parser")
        length = remaining_input[idx]
        if length == 0:
            idx += 1
            break
        if length & 0xC0:
            raise ValueError("Compressed domain names not supported in domain name parser")
        if idx + 1 + length > len(remaining_input):
            raise ValueError("Label length exceeds available bytes in domain name parser")
        label = remaining_input[idx + 1: idx + 1 + length]
        labels.append(label.decode("ascii"))
        idx += 1 + length
    domain_name = ".".join(labels) if labels else "."
    return {"domain_name": domain_name}, remaining_input[idx:]

def parse_packet_resource_record(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a DNS Resource Record from RFC 1035 section 4.1.3.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # Parse NAME (domain name)
    name_result, after_name = parse_packet_domain_name({}, remaining_input)
    # Parse TYPE (2 bytes)
    if len(after_name) < 2:
        raise ValueError("Insufficient bytes for TYPE field")
    rr_type = int.from_bytes(after_name[:2], byteorder='big')
    after_type = after_name[2:]
    # Parse CLASS (2 bytes)
    if len(after_type) < 2:
        raise ValueError("Insufficient bytes for CLASS field")
    rr_class = int.from_bytes(after_type[:2], byteorder='big')
    after_class = after_type[2:]
    # Parse TTL (4 bytes)
    if len(after_class) < 4:
        raise ValueError("Insufficient bytes for TTL field")
    ttl = int.from_bytes(after_class[:4], byteorder='big')
    after_ttl = after_class[4:]
    # Parse RDLENGTH (2 bytes)
    if len(after_ttl) < 2:
        raise ValueError("Insufficient bytes for RDLENGTH field")
    rdlength = int.from_bytes(after_ttl[:2], byteorder='big')
    after_rdlength = after_ttl[2:]
    # Parse RDATA (rdlength bytes)
    if len(after_rdlength) < rdlength:
        raise ValueError(f"Insufficient bytes for RDATA field: need {rdlength}, have {len(after_rdlength)}")
    rdata = after_rdlength[:rdlength]
    remaining_bytes = after_rdlength[rdlength:]
    # Build result dictionary
    result = {
        'name': name_result['domain_name'],
        'type': rr_type,
        'class': rr_class,
        'ttl': ttl,
        'rdlength': rdlength,
        'rdata': rdata
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_rr_route_refresh(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse an RR (Route Refresh) packet as described in RFC 2918 section 4.2.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # RR packet is always 4 bytes
    if len(remaining_input) < 4:
        raise ValueError("RR packet requires at least 4 bytes")

    # Parse the fields
    marker = remaining_input[0]
    length = remaining_input[1]
    type_ = remaining_input[2]
    reserved = remaining_input[3]

    # Validate fields according to RFC 2918
    if marker != 0:
        raise ValueError(f"Marker field must be 0, got {marker}")
    if length != 4:
        raise ValueError(f"Length field must be 4, got {length}")
    if type_ != 1:
        raise ValueError(f"Type field must be 1 for RR, got {type_}")
    if reserved != 0:
        raise ValueError(f"Reserved field must be 0, got {reserved}")

    result = {
        "marker": marker,
        "length": length,
        "type": type_,
        "reserved": reserved
    }
    current_result.update(result)
    remaining_bytes = remaining_input[4:]
    return current_result, remaining_bytes

def parse_packet_standard_rr(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a Standard Resource Record (RR) as described in RFC 1035 section 4.3.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    # Helper function to parse a domain name (possibly compressed)
    def parse_domain_name(data: bytes, offset: int = 0) -> tuple[str, int]:
        labels = []
        pos = offset
        jumped = False
        jump_pos = 0
        while True:
            if pos >= len(data):
                raise ValueError("Truncated domain name")
            length = data[pos]
            if length == 0:
                pos += 1
                break
            # Check for compression pointer
            if (length & 0xC0) == 0xC0:
                if pos + 1 >= len(data):
                    raise ValueError("Truncated compression pointer")
                pointer = ((length & 0x3F) << 8) | data[pos + 1]
                if not jumped:
                    jump_pos = pos + 2
                pos = pointer
                jumped = True
                continue
            else:
                pos += 1
                if pos + length > len(data):
                    raise ValueError("Label length exceeds data size")
                label = data[pos:pos + length].decode('ascii', errors='replace')
                labels.append(label)
                pos += length
        if not jumped:
            return '.'.join(labels), pos
        else:
            return '.'.join(labels), jump_pos

    # Helper function to parse a character-string
    def parse_character_string(data: bytes, offset: int = 0) -> tuple[bytes, int]:
        if offset >= len(data):
            raise ValueError("Truncated character-string")
        length = data[offset]
        if offset + 1 + length > len(data):
            raise ValueError("Character-string length exceeds data size")
        value = data[offset + 1:offset + 1 + length]
        return value, offset + 1 + length

    # Parse NAME (domain name)
    name, pos = parse_domain_name(remaining_input, 0)
    # Parse TYPE (2 bytes)
    if pos + 2 > len(remaining_input):
        raise ValueError("Truncated TYPE field in RR")
    rr_type = int.from_bytes(remaining_input[pos:pos + 2], 'big')
    pos += 2
    # Parse CLASS (2 bytes)
    if pos + 2 > len(remaining_input):
        raise ValueError("Truncated CLASS field in RR")
    rr_class = int.from_bytes(remaining_input[pos:pos + 2], 'big')
    pos += 2
    # Parse TTL (4 bytes)
    if pos + 4 > len(remaining_input):
        raise ValueError("Truncated TTL field in RR")
    ttl = int.from_bytes(remaining_input[pos:pos + 4], 'big')
    pos += 4
    # Parse RDLENGTH (2 bytes)
    if pos + 2 > len(remaining_input):
        raise ValueError("Truncated RDLENGTH field in RR")
    rdlength = int.from_bytes(remaining_input[pos:pos + 2], 'big')
    pos += 2
    # Parse RDATA (rdlength bytes)
    if pos + rdlength > len(remaining_input):
        raise ValueError("Truncated RDATA field in RR")
    rdata = remaining_input[pos:pos + rdlength]
    pos += rdlength
    # For NS, SOA, CNAME, PTR, RDATA contains domain names (possibly compressed)
    # For SOA, RDATA contains two domain names, then 5 32-bit integers
    if rr_type == 1:  # A
        a_result, _ = parse_packet_a_rdata({}, rdata)
        rdata_parsed = a_result
    elif rr_type == 2:  # NS
        ns_result, _ = parse_packet_ns_rdata({}, rdata)
        rdata_parsed = ns_result
    elif rr_type == 5:  # CNAME
        cname_result, _ = parse_packet_cname_rdata({}, rdata)
        rdata_parsed = cname_result
    elif rr_type == 12:  # PTR
        ptr_result, _ = parse_packet_ptr_rdata({}, rdata)
        rdata_parsed = ptr_result
    elif rr_type == 6:  # SOA
        soa_result, _ = parse_packet_soa_rdata({}, rdata)
        rdata_parsed = soa_result
    elif rr_type == 13:  # HINFO
        hinfo_result, _ = parse_packet_hinfo_rdata({}, rdata)
        rdata_parsed = hinfo_result
    elif rr_type == 7:  # MB (EXPERIMENTAL)
        mb_result, _ = parse_packet_mb_rdata({}, rdata)
        rdata_parsed = mb_result
    elif rr_type == 3:  # MD (Obsolete)
        md_result, _ = parse_packet_md_rdata({}, rdata)
        rdata_parsed = md_result
    elif rr_type == 4:  # MF (Obsolete)
        mf_result, _ = parse_packet_mf_rdata({}, rdata)
        rdata_parsed = mf_result
    elif rr_type == 8:  # MG (RFC 1035 4.3.6)
        mg_result, _ = parse_packet_mg_rdata({}, rdata)
        rdata_parsed = mg_result
    elif rr_type == 9:  # MR (RFC 1035 4.3.8)
        mr_result, _ = parse_packet_mr_rdata({}, rdata)
        rdata_parsed = mr_result
    elif rr_type == 14:  # MINFO (RFC 1035 4.3.7)
        minfo_result, _ = parse_packet_minfo_rdata({}, rdata)
        rdata_parsed = minfo_result
    elif rr_type == 15:  # MX (RFC 1035 4.3.9)
        mx_result, _ = parse_packet_mx_rdata({}, rdata)
        rdata_parsed = mx_result
    elif rr_type == 10:  # NULL (RFC 1035 4.3.10)
        null_result, _ = parse_packet_null_rdata({}, rdata)
        rdata_parsed = null_result
    elif rr_type == 16:  # TXT (RFC 1035 4.3.14)
        txt_result, _ = parse_packet_txt_rdata({}, rdata)
        rdata_parsed = txt_result
    elif rr_type == 11:  # WKS
        wks_result, _ = parse_packet_wks_rdata({}, rdata)
        rdata_parsed = wks_result
    else:
        # For other types, just return raw RDATA
        rdata_parsed = {'rdata': rdata}
    result = {
        'name': name,
        'type': rr_type,
        'class': rr_class,
        'ttl': ttl,
        'rdlength': rdlength,
        'rdata': rdata_parsed
    }
    current_result.update(result)
    return current_result, remaining_input[pos:]

def parse_packet_ns_rdata(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse NS RDATA format as specified in RFC 1035 section 4.3.11.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    nsdname = b""
    labels = []
    offset = 0
    while True:
        if offset >= len(remaining_input):
            raise ValueError("Truncated input while parsing NSDNAME domain name")
        length = remaining_input[offset]
        offset += 1
        if length == 0:
            break
        if length & 0xC0 == 0xC0:
            raise ValueError("Compression pointer not allowed in RDATA (NSDNAME)")
        if offset + length > len(remaining_input):
            raise ValueError("Label length exceeds remaining input while parsing NSDNAME")
        label = remaining_input[offset:offset+length]
        labels.append(label)
        offset += length
    nsdname = b'.'.join(labels)
    result = {
        "nsdname_wire": remaining_input[:offset],
        "nsdname_labels": labels,
        "nsdname": nsdname.decode("ascii") if labels else '.'
    }
    current_result.update(result)
    return current_result, remaining_input[offset:]

def parse_packet_cname_rdata(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a CNAME RDATA field as specified in RFC 1035 section 4.3.1.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    def parse_domain_name(data: bytes) -> tuple[str, int]:
        labels = []
        idx = 0
        while True:
            if idx >= len(data):
                raise ValueError("Truncated domain name in CNAME RDATA")
            length = data[idx]
            if length == 0:
                idx += 1
                break
            if (length & 0xC0) == 0xC0:
                raise ValueError("Compression pointer not allowed in CNAME RDATA")
            idx += 1
            if idx + length > len(data):
                raise ValueError("Label length exceeds available data in CNAME RDATA")
            label = data[idx:idx+length].decode('ascii')
            labels.append(label)
            idx += length
        domain_name = '.'.join(labels)
        return domain_name, idx

    cname, consumed = parse_domain_name(remaining_input)
    result = {
        "cname": cname
    }
    current_result.update(result)
    return current_result, remaining_input[consumed:]

def parse_packet_ptr_rdata(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a PTR RDATA packet as specified in RFC 1035 section 4.3.12.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    def parse_domain_name(data: bytes) -> tuple[str, int]:
        labels = []
        idx = 0
        while True:
            if idx >= len(data):
                raise ValueError("Incomplete domain name in PTR RDATA")
            length = data[idx]
            if length == 0:
                idx += 1
                break
            if (length & 0xC0) == 0xC0:
                raise ValueError("Compression pointer not allowed in PTR RDATA domain name")
            if idx + 1 + length > len(data):
                raise ValueError("Label length exceeds available data in PTR RDATA")
            label = data[idx + 1: idx + 1 + length].decode('ascii')
            labels.append(label)
            idx += 1 + length
        return '.'.join(labels), idx

    ptrdname, consumed = parse_domain_name(remaining_input)
    remaining_bytes = remaining_input[consumed:]

    result = {
        "ptrdname": ptrdname
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_hinfo_rdata(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    def parse_character_string(input_bytes: bytes) -> tuple[str, bytes]:
        if not input_bytes:
            raise ValueError("Insufficient bytes for <character-string> length")
        length = input_bytes[0]
        if len(input_bytes) < 1 + length:
            raise ValueError(f"Insufficient bytes for <character-string> of length {length}")
        value = input_bytes[1:1+length].decode("ascii", errors="replace")
        return value, input_bytes[1+length:]
    cpu, rest = parse_character_string(remaining_input)
    os, rest = parse_character_string(rest)
    result = {
        "cpu": cpu,
        "os": os
    }
    current_result.update(result)
    return current_result, rest

def parse_packet_mb_rdata(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    madname = b""
    offset = 0
    labels = []
    while True:
        if offset >= len(remaining_input):
            raise ValueError("Insufficient bytes for domain-name (MADNAME) in MB RDATA")
        label_len = remaining_input[offset]
        offset += 1
        if label_len == 0:
            break
        if offset + label_len > len(remaining_input):
            raise ValueError("Label length exceeds available bytes in MB RDATA")
        label = remaining_input[offset:offset + label_len]
        labels.append(label)
        offset += label_len
    madname = b".".join(labels)
    remaining_bytes = remaining_input[offset:]
    result = {
        "madname": madname
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_md_rdata(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    if not isinstance(remaining_input, bytes):
        raise ValueError("remaining_input must be bytes")
    madname_result, remaining_bytes = parse_packet_domain_name({}, remaining_input)
    result = {
        "madname": madname_result.get("domain_name"),
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_mf_rdata(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    if not remaining_input:
        raise ValueError("No input data to parse for MF RDATA")
    madname_labels = []
    idx = 0
    while True:
        if idx >= len(remaining_input):
            raise ValueError("Incomplete domain-name in MF RDATA")
        length = remaining_input[idx]
        if length == 0:
            idx += 1
            break
        if length & 0xC0 == 0xC0:
            raise ValueError("Compression pointer not allowed in MF RDATA domain-name")
        if idx + 1 + length > len(remaining_input):
            raise ValueError("Label length exceeds available data in MF RDATA")
        label = remaining_input[idx + 1 : idx + 1 + length]
        madname_labels.append(label)
        idx += 1 + length
    madname = b'.'.join(madname_labels)
    remaining_bytes = remaining_input[idx:]
    result = {
        "madname": madname
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_mg_rdata(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    if len(remaining_input) == 0:
        raise ValueError("No bytes left to parse MGMNAME domain-name")
    mgmname_result, remaining_bytes = parse_packet_domain_name({}, remaining_input)
    result = {
        "mgmname": mgmname_result["domain_name"] if "domain_name" in mgmname_result else mgmname_result
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_minfo_rdata(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    rmailbx_result, remaining = parse_packet_domain_name({}, remaining_input)
    rmailbx = rmailbx_result["domain_name"]
    emailbx_result, remaining = parse_packet_domain_name({}, remaining)
    emailbx = emailbx_result["domain_name"]
    result = {
        "rmailbx": rmailbx,
        "emailbx": emailbx,
    }
    current_result.update(result)
    return current_result, remaining

def parse_packet_mr_rdata(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    if not remaining_input:
        raise ValueError("No input data to parse MR RDATA")
    newname_result, remaining_bytes = parse_packet_domain_name({}, remaining_input)
    result = {
        "newname": newname_result.get("domain_name"),
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_mx_rdata(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    if len(remaining_input) < 3:
        raise ValueError("MX RDATA requires at least 3 bytes (2 for preference, 1 for exchange)")
    preference = int.from_bytes(remaining_input[:2], byteorder="big")
    exchange_bytes = remaining_input[2:]
    labels = []
    idx = 0
    while True:
        if idx >= len(exchange_bytes):
            raise ValueError("Incomplete domain name in EXCHANGE field")
        label_len = exchange_bytes[idx]
        if label_len == 0:
            idx += 1
            break
        if idx + 1 + label_len > len(exchange_bytes):
            raise ValueError("Label length exceeds available bytes in EXCHANGE field")
        label = exchange_bytes[idx + 1 : idx + 1 + label_len]
        labels.append(label.decode("ascii"))
        idx += 1 + label_len
    exchange = ".".join(labels) + "." if labels else ""
    remaining_bytes = exchange_bytes[idx:]
    result = {
        "preference": preference,
        "exchange": exchange,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_null_rdata(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    rdata_length = len(remaining_input)
    if rdata_length > 65535:
        raise ValueError(f"NULL RDATA length {rdata_length} exceeds 65535 octets")
    rdata = remaining_input[:rdata_length]
    remaining_bytes = remaining_input[rdata_length:]
    result = {
        "rdata": rdata
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_soa_rdata(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse SOA RDATA from DNS packet according to RFC 1035 section 4.3.13.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    def parse_packet_domain_name(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
        labels = []
        idx = 0
        while True:
            if idx >= len(remaining_input):
                raise ValueError("Truncated domain name in SOA RDATA")
            length = remaining_input[idx]
            if length == 0:
                idx += 1
                break
            if (length & 0xC0) == 0xC0:
                raise ValueError("Compression pointer not allowed in SOA RDATA domain name")
            if idx + 1 + length > len(remaining_input):
                raise ValueError("Label length exceeds available data in SOA RDATA domain name")
            label = remaining_input[idx + 1 : idx + 1 + length]
            labels.append(label)
            idx += 1 + length
        domain_name = b".".join(labels)
        return {"domain_name": domain_name}, remaining_input[idx:]

    mname_result, remaining = parse_packet_domain_name({}, remaining_input)
    mname = mname_result["domain_name"]
    rname_result, remaining = parse_packet_domain_name({}, remaining)
    rname = rname_result["domain_name"]
    if len(remaining) < 20:
        raise ValueError("SOA RDATA requires at least 20 bytes for SERIAL, REFRESH, RETRY, EXPIRE, MINIMUM")
    serial = int.from_bytes(remaining[0:4], byteorder="big")
    refresh = int.from_bytes(remaining[4:8], byteorder="big", signed=False)
    retry = int.from_bytes(remaining[8:12], byteorder="big", signed=False)
    expire = int.from_bytes(remaining[12:16], byteorder="big", signed=False)
    minimum = int.from_bytes(remaining[16:20], byteorder="big", signed=False)
    remaining_bytes = remaining[20:]
    result = {
        "mname": mname,
        "rname": rname,
        "serial": serial,
        "refresh": refresh,
        "retry": retry,
        "expire": expire,
        "minimum": minimum,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_txt_rdata(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a DNS TXT RDATA packet according to RFC 1035 section 4.3.14.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    txt_data = []
    offset = 0
    while offset < len(remaining_input):
        if len(remaining_input) - offset < 1:
            raise ValueError("Insufficient bytes for TXT-DATA length field")
        length = remaining_input[offset]
        offset += 1
        if len(remaining_input) - offset < length:
            raise ValueError(f"Insufficient bytes for TXT-DATA string of length {length}")
        string = remaining_input[offset:offset+length]
        txt_data.append(string)
        offset += length
    result = {
        "txt_data": txt_data
    }
    current_result.update(result)
    remaining_bytes = remaining_input[offset:]
    return current_result, remaining_bytes

def parse_packet_dns_rr_type(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a DNS Resource Record TYPE field from RFC 1035 section 4.2.2.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    if len(remaining_input) < 2:
        raise ValueError("Insufficient bytes for DNS RR TYPE field (need 2 bytes)")

    type_value = int.from_bytes(remaining_input[:2], byteorder="big")
    remaining_bytes = remaining_input[2:]

    type_map = {
        1: "A",
        2: "NS",
        3: "MD",
        4: "MF",
        5: "CNAME",
        6: "SOA",
        7: "MB",
        8: "MG",
        9: "MR",
        10: "NULL",
        11: "WKS",
        12: "PTR",
        13: "HINFO",
        14: "MINFO",
        15: "MX",
        16: "TXT",
    }

    if type_value not in type_map:
        raise ValueError(f"Unknown or unsupported DNS RR TYPE value: {type_value}")

    result = {
        "type_value": type_value,
        "type_name": type_map[type_value],
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_class_field(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a CLASS field from DNS resource record as per RFC 1035 section 4.2.4.

    Args:
        current_result: Dictionary containing already parsed fields
        remaining_input: Bytes to parse

    Returns:
        Tuple of (parsed_fields_dict, remaining_bytes)

    Raises:
        ValueError: If the input data doesn't conform to RFC specifications
    """
    if len(remaining_input) < 2:
        raise ValueError("CLASS field requires at least 2 bytes")

    class_value = int.from_bytes(remaining_input[:2], byteorder="big")
    remaining_bytes = remaining_input[2:]

    class_mnemonics = {
        1: "IN",
        2: "CS",
        3: "CH",
        4: "HS",
    }
    class_mnemonic = class_mnemonics.get(class_value, None)

    result = {
        "class_value": class_value,
        "class_mnemonic": class_mnemonic,
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_internet_specific_rrs(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse Internet specific Resource Records (RRs) as described in RFC 1035 section 4.4.
    """
    def parse_domain_name(data: bytes) -> tuple[str, int]:
        labels = []
        idx = 0
        while True:
            if idx >= len(data):
                raise ValueError("Incomplete domain name in RR")
            length = data[idx]
            if length == 0:
                idx += 1
                break
            if (length & 0xC0) == 0xC0:
                if idx + 1 >= len(data):
                    raise ValueError("Incomplete pointer in domain name")
                pointer = ((length & 0x3F) << 8) | data[idx + 1]
                raise ValueError("Domain name compression not supported in this parser")
            else:
                idx += 1
                if idx + length > len(data):
                    raise ValueError("Label length exceeds available data")
                label = data[idx:idx+length].decode('ascii')
                labels.append(label)
                idx += length
        return '.'.join(labels), idx
    name, name_len = parse_domain_name(remaining_input)
    offset = name_len
    if len(remaining_input) < offset + 10:
        raise ValueError("Not enough bytes for RR header after NAME")
    rr_type = int.from_bytes(remaining_input[offset:offset+2], 'big')
    offset += 2
    rr_class = int.from_bytes(remaining_input[offset:offset+2], 'big')
    offset += 2
    ttl = int.from_bytes(remaining_input[offset:offset+4], 'big')
    offset += 4
    rdlength = int.from_bytes(remaining_input[offset:offset+2], 'big')
    offset += 2
    if len(remaining_input) < offset + rdlength:
        raise ValueError("Not enough bytes for RDATA")
    rdata = remaining_input[offset:offset+rdlength]
    offset += rdlength
    result = {
        'name': name,
        'type': rr_type,
        'class': rr_class,
        'ttl': ttl,
        'rdlength': rdlength,
        'rdata': rdata
    }
    current_result.update(result)
    return current_result, remaining_input[offset:]

def parse_packet_a_rdata(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse an A RDATA record from RFC specification (IPv4 address).
    """
    if len(remaining_input) < 4:
        raise ValueError("A RDATA requires at least 4 bytes for ADDRESS field")
    address_bytes = remaining_input[:4]
    remaining_bytes = remaining_input[4:]
    address = ".".join(str(b) for b in address_bytes)
    result = {
        "address": address_bytes,
        "address_str": address
    }
    current_result.update(result)
    return current_result, remaining_bytes

def parse_packet_wks_rdata(current_result: dict, remaining_input: bytes) -> tuple[dict, bytes]:
    """
    Parse a WKS RDATA record as specified in RFC 1035 section 4.4.2.
    """
    if len(remaining_input) < 5:
        raise ValueError("WKS RDATA requires at least 5 bytes (4 for ADDRESS, 1 for PROTOCOL)")
    address_bytes = remaining_input[:4]
    address = ".".join(str(b) for b in address_bytes)
    protocol = remaining_input[4]
    bitmap = remaining_input[5:]
    if len(bitmap) == 0:
        raise ValueError("WKS RDATA BIT MAP must not be empty")
    if len(bitmap) % 1 != 0:
        raise ValueError("WKS RDATA BIT MAP must be a multiple of 8 bits (whole bytes)")
    remaining_bytes = b""
    result = {
        "address": address,
        "protocol": protocol,
        "bitmap": bitmap,
    }
    current_result.update(result)
    return current_result, remaining_bytes

import sys

def main():
    try:
        with open(sys.argv[1], "rb") as f:
            data = f.read()
        result, remaining = parse_packet_dns_header({}, data)
        # Parse question section(s) if present
        if result.get("qdcount", 0) > 0:
            for _ in range(result["qdcount"]):
                result, remaining = parse_packet_question_section(result, remaining)
        # Parse answer section(s) if present
        if result.get("ancount", 0) > 0:
            for _ in range(result["ancount"]):
                rr_result, remaining = parse_packet_standard_rr({}, remaining)
                if "answers" not in result:
                    result["answers"] = []
                result["answers"].append(rr_result)
        # Parse authority section(s) if present
        if result.get("nscount", 0) > 0:
            for _ in range(result["nscount"]):
                rr_result, remaining = parse_packet_standard_rr({}, remaining)
                if "authorities" not in result:
                    result["authorities"] = []
                result["authorities"].append(rr_result)
        # Parse additional section(s) if present
        if result.get("arcount", 0) > 0:
            for _ in range(result["arcount"]):
                rr_result, remaining = parse_packet_standard_rr({}, remaining)
                if "additionals" not in result:
                    result["additionals"] = []
                result["additionals"].append(rr_result)
        print(result)
    except Exception as e:
        print(str(e))
        import traceback
        traceback.print_exc()
        print(locals().get('result', {}))
        sys.exit(1)

if __name__ == "__main__":
    main()

