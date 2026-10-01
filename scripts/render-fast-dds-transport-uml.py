#!/usr/bin/env python3
"""Render the combined Fast DDS transport/resource ownership UML diagram."""

from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "images" / "fast_dds_transport_resource_ownership_uml.svg"


class Diagram:
    """Fixed-layout SVG builder with explicit paint-order layers."""

    def __init__(self, height: int, title: str):
        self.width = 1400
        self.height = height
        self.title = title
        self.backgrounds: list[str] = []
        self.connectors: list[str] = []
        self.foreground: list[str] = []

    def group(self, x: int, y: int, width: int, height: int, title: str) -> None:
        self.backgrounds.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="10" '
            'fill="#f8fafc" stroke="#94a3b8" stroke-dasharray="6,4"/>'
        )
        label_width = len(title) * 6.3 + 12
        self.foreground.append(
            f'<rect x="{x + 7}" y="{y + 4}" width="{label_width:.1f}" height="18" '
            'rx="3" fill="#f8fafc"/>'
            f'<text x="{x + 10}" y="{y + 16}" class="group-title">{escape(title)}</text>'
        )

    def box(
            self,
            x: int,
            y: int,
            width: int,
            height: int,
            title: str,
            body: tuple[str, ...] = (),
            semantic: str = "primary") -> None:
        colors = {
            "primary": ("#dbeafe", "#3b82f6", "#1e40af"),
            "process": ("#fef3c7", "#f59e0b", "#b45309"),
            "transport": ("#ede9fe", "#8b5cf6", "#6d28d9"),
            "data": ("#d1fae5", "#22c55e", "#166534"),
            "neutral": ("#ffffff", "#64748b", "#1e293b"),
        }
        fill, stroke, title_color = colors[semantic]
        center = x + width / 2
        parts = [
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="7" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1.4"/>',
        ]
        if body:
            parts.extend((
                f'<text x="{center}" y="{y + 18}" class="box-title" fill="{title_color}" '
                f'text-anchor="middle">{escape(title)}</text>',
                f'<line x1="{x}" y1="{y + 28}" x2="{x + width}" y2="{y + 28}" '
                f'stroke="{stroke}" stroke-width="1"/>',
            ))
            for index, line in enumerate(body):
                parts.append(
                    f'<text x="{center}" y="{y + 44 + index * 14}" class="box-body" '
                    f'fill="#334155" text-anchor="middle">{escape(line)}</text>'
                )
        else:
            baseline = y + height / 2 + 4
            parts.append(
                f'<text x="{center}" y="{baseline}" class="box-title" fill="{title_color}" '
                f'text-anchor="middle">{escape(title)}</text>'
            )
        self.foreground.append("".join(parts))

    def path(
            self,
            data: str,
            label: str = "",
            label_x: float = 0,
            label_y: float = 0,
            marker_start: str = "",
            marker_end: str = "arrow",
            dashed: bool = False,
            label_anchor: str = "middle") -> None:
        start = f' marker-start="url(#{marker_start})"' if marker_start else ""
        end = f' marker-end="url(#{marker_end})"' if marker_end else ""
        dash = ' stroke-dasharray="5,4"' if dashed else ""
        self.connectors.append(
            f'<path d="{data}" fill="none" stroke="#64748b" stroke-width="1.4"'
            f'{dash}{start}{end}/>'
        )
        if label:
            self.foreground.append(
                f'<text x="{label_x}" y="{label_y}" class="edge-label" '
                f'text-anchor="{label_anchor}">{escape(label)}</text>'
            )

    def render(self, output: Path) -> None:
        definitions = """
<defs>
  <marker id="arrow" markerWidth="8" markerHeight="8" refX="2" refY="4"
          orient="auto" markerUnits="userSpaceOnUse">
    <path d="M0,0 L8,4 L0,8 L2,4 z" fill="#64748b"/>
  </marker>
  <marker id="triangle" markerWidth="10" markerHeight="10" refX="8" refY="5"
          orient="auto" markerUnits="userSpaceOnUse">
    <path d="M1,1 L9,5 L1,9 z" fill="#ffffff" stroke="#64748b"/>
  </marker>
  <marker id="diamond-filled" markerWidth="12" markerHeight="10" refX="6" refY="5"
          orient="auto" markerUnits="userSpaceOnUse">
    <path d="M0,5 L6,1 L12,5 L6,9 z" fill="#475569"/>
  </marker>
  <marker id="diamond-open" markerWidth="12" markerHeight="10" refX="6" refY="5"
          orient="auto" markerUnits="userSpaceOnUse">
    <path d="M0,5 L6,1 L12,5 L6,9 z" fill="#ffffff" stroke="#64748b"/>
  </marker>
</defs>
<style>
  text { font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', system-ui, sans-serif; }
  .diagram-title { font-size: 16px; font-weight: 700; fill: #1e293b; }
  .group-title { font-size: 11px; font-weight: 600; fill: #64748b; }
  .box-title { font-size: 11px; font-weight: 700; }
  .box-body { font-size: 10px; }
  .edge-label { font-size: 10px; fill: #64748b; }
</style>
"""
        body = (
            '<rect width="100%" height="100%" fill="#ffffff"/>'
            f'<text x="{self.width / 2}" y="32" class="diagram-title" text-anchor="middle">'
            f'{escape(self.title)}</text>'
            + "".join(self.backgrounds)
            + "".join(self.connectors)
            + "".join(self.foreground)
        )
        output.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" '
            f'viewBox="0 0 {self.width} {self.height}" role="img" aria-label="{escape(self.title)}">'
            f'{definitions}{body}</svg>\n',
            encoding="utf-8",
        )


def render() -> None:
    d = Diagram(3267, "Fast DDS transport, resource, channel, and backing relationships")

    d.group(20, 52, 1360, 135, "PARTICIPANT")
    d.group(20, 212, 1360, 170, "PARTICIPANT-OWNED NETWORK OBJECTS")
    d.group(20, 407, 1360, 165, "COMMON ABSTRACTIONS")
    d.group(10, 582, 1380, 520, "SENDER RESOURCE PREPARATION TO REACH A REMOTE ENDPOINT")
    d.group(25, 612, 1350, 135, "PARTICIPANT AND NETWORKFACTORY — DESTINATION LOCATOR TO TRANSPORT ITERATION")
    d.group(25, 752, 1350, 335,
            "PER TRANSPORT INSTANCE — OPENOUTPUTCHANNEL() REUSES OR APPENDS TO PARTICIPANT send_resource_list_")
    d.group(20, 1112, 1360, 450, "OUTGOING DATA AND DESTINATION DISPATCH")
    d.group(10, 1582, 1380, 845, "RECEIVER SETUP FOR ONE LOCALLY CREATED ENDPOINT")
    d.group(25, 1612, 1350, 680, "PHASE 1 — CREATE OR REUSE RECEIVE REGISTRATIONS")
    d.group(25, 2307, 1350, 105, "PHASE 2 — ASSOCIATE ENDPOINT WITH MATCHING CONTROL BLOCKS")
    d.group(20, 2442, 1360, 800, "INCOMING DATA AND ENDPOINT DISPATCH")
    d.group(30, 2874, 1340, 350, "MESSAGERECEIVER SUBMESSAGE PARSING AND LOCAL ENDPOINT DISPATCH")

    d.box(350, 82, 700, 80, "RTPSParticipantImpl",
          ("m_network_Factory: NetworkFactory",
           "send_resource_list_: vector<unique_ptr<SenderResource>>",
           "m_receiverResourcelist: list<ReceiverControlBlock>"), "primary")

    participant_objects = (
        (40, "NetworkFactory", ("mRegisteredTransports:",
                                "std::vector<std::unique_ptr<TransportInterface>>")),
        (375, "SenderResource", ("int32_t transport_kind_", "std::function<void()> clean_up",
                                 "std::function send_buffers_lambda_", "std::function send_lambda_")),
        (710, "ReceiverControlBlock", ("std::shared_ptr<ReceiverResource> Receiver",
                                       "MessageReceiver* mp_receiver")),
        (1045, "MessageReceiver", ("std::vector<BaseWriter*> associated_writers_",
                                   "std::unordered_map<EntityId_t,",
                                   "std::vector<BaseReader*>> associated_readers_")),
    )
    for x, title, body in participant_objects:
        d.box(x, 247, 310, 110, title, body, "primary")

    d.box(40, 442, 310, 105, "TransportInterface",
          ("int32_t transport_kind_", "OpenInputChannel()", "OpenOutputChannel()"), "process")
    d.box(375, 442, 310, 105, "ReceiverResource",
          ("std::function<void()> Cleanup", "std::function<bool(const Locator_t&)>",
           "LocatorMapsToManagedChannel", "MessageReceiver* receiver"), "data")
    d.box(710, 442, 310, 105, "TransportReceiverInterface",
          ("no data members", "OnDataReceived()"), "process")
    d.box(1045, 442, 310, 105, "Locator",
          ("int32_t kind", "uint32_t port", "octet address[16]"), "neutral")

    participant_relations = (
        (500, 195, "1", 405),
        (700, 530, "0..*", 615),
        (900, 865, "0..*", 880),
    )
    for start_x, end_x, cardinality, label_x in participant_relations:
        d.path(
            f"M{start_x},167 C{start_x},207 {end_x},212 {end_x},242",
            cardinality,
            label_x,
            211,
            marker_start="diamond-filled",
            marker_end="",
        )
    d.path("M1025,302 L1040,302", "1", 1032, 293,
           marker_start="diamond-filled", marker_end="")
    d.path("M195,362 L195,431", marker_start="diamond-filled")
    d.path("M865,362 C865,400 530,400 530,431", "1", 700, 390,
           marker_start="diamond-open", marker_end="")
    d.path("M690,494 L699,494", marker_end="triangle")

    sender_setup_steps = (
        (40, "Remote endpoint to reach", ("matched remote reader or writer",
                                           "bootstrap: configured initial destination")),
        (310, "Remote endpoint locators", ("proxy remote_locators: unicast + multicast",
                                            "filter with local endpoint attributes")),
        (580, "Prepare outgoing resources", ("createSenderResources(",
                                               "RemoteLocatorList, attributes)",
                                               "bootstrap uses createSendResources(Endpoint*)")),
        (850, "For each selected remote locator", ("lock m_send_resources_mutex_",
                                                     "resources remain participant-wide")),
        (1120, "For each registered transport", ("transport in mRegisteredTransports",
                                                   "OpenOutputChannel(send_resource_list_, locator)")),
    )
    for x, title, body in sender_setup_steps:
        d.box(x, 642, 235, 92, title, body, "process")
    for start_x, end_x in ((275, 299), (545, 569), (815, 839), (1085, 1109)):
        d.path(f"M{start_x},688 L{end_x},688")

    udp_output_steps = (
        (40, "UDP OpenOutputChannel()", ("UDPv4Transport or UDPv6Transport",)),
        (310, "Find missing local interfaces", ("get_unknown_network_interfaces()",
                                                  "reuse existing UDP resources")),
        (580, "Choose output bindings", ("wildcard when no allowlist",
                                           "otherwise allowed interfaces")),
        (850, "Create each missing output socket", ("OpenAndBindUnicastOutputSocket()",
                                                      "set outbound interface")),
        (1120, "Append UDPSenderResource", ("send_resource_list_.emplace_back()",
                                             "resource owns the socket")),
    )
    tcp_output_steps = (
        (40, "TCP OpenOutputChannel()", ("TCPv4Transport or TCPv6Transport",)),
        (310, "Resolve destination identity", ("physical locator selects connection",
                                                 "logical port selects remote receiver")),
        (580, "Reuse existing TCPSenderResource", ("key: remote physical locator or WAN alias",
                                                     "logical port is not part of reuse key",
                                                     "add it to channel or pending-port set")),
        (850, "Otherwise prepare connection", ("reuse accepted TCPChannelResource,",
                                                 "initiate connection, or wait for peer")),
        (1120, "Append TCPSenderResource", ("physical locator + weak channel reference",
                                             "send_resource_list_.emplace_back()",
                                             "channel reference may initially be empty")),
    )
    shm_output_steps = (
        (40, "SHM OpenOutputChannel()", ("SharedMemTransport",)),
        (310, "Validate locator kind", ("IsLocatorSupported(locator)",)),
        (580, "Scan participant sender list", ("SharedMemSenderResource::cast()",
                                                 "reuse if already present")),
        (850, "Create only when missing", ("new SharedMemSenderResource(*this)",
                                            "no destination port opened yet")),
        (1120, "Append shared SHM resource", ("send_resource_list_.emplace_back()",
                                               "one per SHM transport instance")),
    )
    for y, steps in ((782, udp_output_steps), (884, tcp_output_steps), (986, shm_output_steps)):
        for x, title, body in steps:
            d.box(x, y, 235, 90, title, body, "transport")
        for start_x, end_x in ((275, 299), (545, 569), (815, 839), (1085, 1109)):
            d.path(f"M{start_x},{y + 45} L{end_x},{y + 45}")

    outgoing_steps = (
        (40, "RTPS endpoint", ("forms message buffers",)),
        (310, "Selected destination locators", ("remote unicast and multicast locators",)),
        (580, "RTPSParticipantImpl::sendSync()", ("lock m_send_resources_mutex_",)),
        (850, "For each SenderResource", ("copy fresh locator iterators",
                                            "visit the whole participant list")),
        (1120, "SenderResource::send()", ("invoke transport-bound send_lambda_",
                                           "each resource filters destinations")),
    )
    for x, title, body in outgoing_steps:
        d.box(x, 1147, 235, 80, title, body, "data")
    for start_x, end_x in ((275, 299), (545, 569), (815, 839), (1085, 1109)):
        d.path(f"M{start_x},1187 L{end_x},1187")

    udp_send_steps = (
        (40, "UDPSenderResource", ("socket_ + interface-purpose flags",)),
        (310, "Filter each destination", ("UDP kind, multicast purpose,",
                                            "allowlist and netmask")),
        (580, "Build destination endpoint", ("generate_endpoint(remote_locator,",
                                               "physical UDP port)")),
        (850, "Send datagram", ("socket_.send_to(buffers, endpoint)",)),
        (1120, "Remote UDP destination", ("destination IP + physical UDP port",
                                           "receives one RTPS datagram")),
    )
    tcp_send_steps = (
        (40, "TCPSenderResource", ("locator_ = remote physical locator",)),
        (310, "Filter each destination", ("TCP kind and matching physical locator",)),
        (580, "Find established connection", ("channel_resources_.find(locator_)",
                                                "accepted or locally initiated")),
        (850, "Prepare framed message", ("open remote logical port if needed",
                                          "TCPHeader carries logical port")),
        (1120, "Send on bidirectional channel", ("TCPChannelResource::send()",
                                                   "connection socket writes bytes")),
    )
    shm_send_steps = (
        (40, "SharedMemSenderResource", ("delegates to SharedMemTransport",)),
        (310, "Filter each destination", ("shared-memory locator kind",)),
        (580, "Allocate payload once", ("copy_to_shared_buffer()",
                                         "reuse buffer for all destinations")),
        (850, "Find or open destination port", ("find_port(remote_locator.port)",
                                                  "cache in opened_ports_")),
        (1120, "Publish buffer descriptor", ("SharedMemManager::Port::try_push()",)),
    )
    for y, steps in ((1250, udp_send_steps), (1350, tcp_send_steps), (1450, shm_send_steps)):
        for x, title, body in steps:
            d.box(x, y, 235, 84, title, body, "transport")
        for start_x, end_x in ((275, 299), (545, 569), (815, 839), (1085, 1109)):
            d.path(f"M{start_x},{y + 42} L{end_x},{y + 42}")

    registration_steps = (
        (40, "Local endpoint created or enabled", ("reader: receive data",
                                                     "reliable writer: receive feedback")),
        (310, "createAndAssociateReceiverswithEndpoint()", ("argument: Endpoint* pend",)),
        (580, "createReceiverResources(list)", ("local unicast list, then multicast list",
                                                  "for each locator in input_list")),
        (850, "BuildReceiverResources(locator)", ("NetworkFactory handles current locator",
                                                    "iterate mRegisteredTransports")),
        (1120, "Per-transport decision", ("unsupported: skip",
                                           "open: reuse; return no resource",
                                           "missing: follow creation row")),
    )
    for x, title, body in registration_steps:
        d.box(x, 1642, 235, 92, title, body, "process")
    for start_x, end_x in ((275, 299), (545, 569), (815, 839)):
        d.path(f"M{start_x},1688 L{end_x},1688")
    d.path("M1085,1688 L1109,1688")

    channel_creation_steps = (
        (40, "Missing registration path", ("IsInputChannelOpen(locator) is false",)),
        (310, "ReceiverResource constructor", ("captures this transport and locator",)),
        (580, "OpenInputChannel(locator, this)", ("this is the ReceiverResource*",
                                                    "passed as TransportReceiverInterface*")),
        (850, "Concrete transport implementation", ("follow exactly one row below",)),
    )
    for x, title, body in channel_creation_steps:
        d.box(x, 1757, 235, 84, title, body, "process")
    for start_x, end_x in ((275, 299), (545, 569), (815, 839)):
        d.path(f"M{start_x},1799 L{end_x},1799")
    d.path("M1238,1739 L1238,1747 L158,1747 L158,1751", "missing", 700, 1745,
           marker_end="arrow")

    udp_input_steps = (
        (40, "UDP OpenInputChannel()", ("UDPv4Transport or UDPv6Transport",)),
        (310, "Validate and check registry", ("IsLocatorSupported() and is_locator_allowed()",
                                                "IsInputChannelOpen(locator)")),
        (580, "Get binding entries", ("get_binding_interfaces_list()",
                                       "wildcard or whitelisted addresses")),
        (850, "For each binding entry", ("CreateInputChannelResource()",
                                          "create socket + UDPChannelResource")),
        (1120, "Store UDP input backing", ("mInputSockets[physical port]",
                                            "stores UDPChannelResource*",
                                            "message_receiver_ = receiver",
                                            "receiver points to ReceiverResource")),
    )
    tcp_input_steps = (
        (40, "TCP OpenInputChannel()", ("TCPv4Transport or TCPv6Transport",)),
        (310, "Validate locator", ("IsLocatorSupported(locator)",)),
        (580, "Extract logical port", ("getLogicalPort(locator)",
                                        "transport has 0..1 physical listening port",
                                        "acceptor sockets already exist per interface")),
        (850, "Check logical-port registry", ("is_input_port_open(logical_port)",
                                               "open registration: create nothing")),
        (1120, "Store TCP callback pair", ("receiver_resources_[logical_port]",
                                            "receiver points to ReceiverResource",
                                            "+ new ReceiverInUseCV()",
                                            "creates no TCPChannelResource")),
    )
    shm_input_steps = (
        (40, "SHM OpenInputChannel()", ("SharedMemTransport",)),
        (310, "Validate and check registry", ("IsLocatorSupported(locator)",
                                                "IsInputChannelOpen(locator)")),
        (580, "Open shared-memory port", ("shared_mem_manager_->open_port()",
                                           "port = locator.port")),
        (850, "Create listener and channel", ("Port::create_listener()",
                                               "new SharedMemChannelResource")),
        (1120, "Store SHM input backing", ("input_channels_",
                                            "stores SharedMemChannelResource*",
                                            "message_receiver_ = receiver",
                                            "receiver points to ReceiverResource")),
    )
    for y, steps in ((1866, udp_input_steps), (1979, tcp_input_steps), (2092, shm_input_steps)):
        for x, title, body in steps:
            d.box(x, y, 235, 96, title, body, "transport")
        for start_x, end_x in ((275, 299), (545, 569), (815, 839), (1085, 1109)):
            d.path(f"M{start_x},{y + 48} L{end_x},{y + 48}")

    completion_steps = (
        (40, "Back in participant setup", ("selected transport row returned true",)),
        (310, "Return ReceiverResource", ("BuildReceiverResources() result",)),
        (580, "Create ReceiverControlBlock", ("store shared_ptr<ReceiverResource>",)),
        (850, "Create MessageReceiver", ("store in block.mp_receiver",)),
        (1120, "Register callback target", ("ReceiverResource::RegisterReceiver()",
                                             "argument: MessageReceiver*")),
    )
    for x, title, body in completion_steps:
        d.box(x, 2205, 235, 70, title, body, "process")
    for start_x, end_x in ((275, 299), (545, 569), (815, 839), (1085, 1109)):
        d.path(f"M{start_x},2240 L{end_x},2240")

    association_steps = (
        (40, "assignEndpointListenResources()", ("same Endpoint* pend",
                                                  "starts after both lists are prepared")),
        (310, "assignEndpoint2LocatorList(list)", ("called for local unicast list,",
                                                    "then local multicast list")),
        (580, "for each locator in list", ("second pass over effective locators",)),
        (850, "for each ReceiverControlBlock", ("block in m_receiverResourcelist",
                                                 "scan the participant-wide registry")),
        (1120, "ReceiverResource::SupportsLocator()", ("true: MessageReceiver::associateEndpoint()",
                                                        "false: continue scanning")),
    )
    for x, title, body in association_steps:
        d.box(x, 2337, 235, 72, title, body, "data")
    for start_x, end_x in ((275, 299), (545, 569), (815, 839), (1085, 1109)):
        d.path(f"M{start_x},2373 L{end_x},2373")

    dispatch_steps = (
        (40, "Transport input path", ("UDP/SHM channel callback or",
                                       "TCP logical-port dispatch")),
        (310, "ReceiverResource::OnDataReceived()", ("data, size, local_locator,",
                                                       "remote_locator")),
        (580, "Wrap CDRMessage_t", ("reference received buffer; no payload copy",)),
        (850, "MessageReceiver::processCDRMsg()", ("source = remote; reception = local",)),
        (1120, "Dispatch RTPS submessage", ("reader EntityId → associated_readers_",
                                             "ACKNACK/NACK_FRAG → associated_writers_")),
    )
    for x, title, body in dispatch_steps:
        d.box(x, 2477, 235, 70, title, body, "data")
    for start_x, end_x in ((275, 299), (545, 569), (815, 839), (1085, 1109)):
        d.path(f"M{start_x},2512 L{end_x},2512")

    udp_receive_steps = (
        (40, "UDPChannelResource listen thread", ("one thread for this socket channel",)),
        (310, "Receive UDP datagram", ("socket_.receive_from()",
                                        "fill channel message buffer")),
        (580, "Build reception locators", ("input_locator captured at channel creation",
                                             "sender endpoint → remote_locator")),
        (850, "Use stored callback pointer", ("message_receiver_",
                                                "points to ReceiverResource")),
        (1120, "Invoke receive adapter", ("OnDataReceived(buffer, size,",
                                            "input_locator, remote_locator)")),
    )
    tcp_receive_steps = (
        (40, "TCPChannelResource listen thread", ("accepted or locally initiated connection",)),
        (310, "Read framed TCP message", ("read TCPHeader and body",
                                           "logical port 0 handles RTCP control")),
        (580, "Select logical registration", ("logical_port = TCPHeader.logical_port",
                                                "receiver_resources_.find(logical_port)")),
        (850, "Protect and load callback", ("ReceiverInUseCV::in_use++",
                                             "pair.first points to ReceiverResource")),
        (1120, "Invoke receive adapter", ("OnDataReceived(buffer, size,",
                                            "channel->locator(), remote_locator)")),
    )
    shm_receive_steps = (
        (40, "SharedMemChannelResource thread", ("listener for this SHM input port",)),
        (310, "Receive shared buffer", ("listener_->pop()",
                                         "obtain SharedMemManager::Buffer")),
        (580, "Build reception locators", ("input_locator captured at creation",
                                             "remote_locator.kind = LOCATOR_KIND_SHM")),
        (850, "Use stored callback pointer", ("message_receiver_",
                                                "points to ReceiverResource")),
        (1120, "Invoke receive adapter", ("OnDataReceived(message->data(), size,",
                                            "input_locator, remote_locator)")),
    )
    for y, steps in ((2570, udp_receive_steps), (2670, tcp_receive_steps), (2770, shm_receive_steps)):
        for x, title, body in steps:
            d.box(x, y, 235, 84, title, body, "transport")
        for start_x, end_x in ((275, 299), (545, 569), (815, 839), (1085, 1109)):
            d.path(f"M{start_x},{y + 42} L{end_x},{y + 42}")

    submessage_parse_steps = (
        (40, "MessageReceiver::processCDRMsg()", ("one RTPS message buffer",)),
        (310, "Validate RTPS message header", ("checkRTPSHeader()",
                                                  "initialize source and destination context")),
        (580, "Iterate RTPS submessages", ("while bytes remain",
                                             "readSubmessageHeader()")),
        (850, "Select submessage handler", ("switch (submessageId)",
                                              "call proc_Submsg_*()")),
        (1120, "Choose endpoint direction", ("reader-directed traffic or",
                                               "writer-directed reliability feedback")),
    )
    reader_dispatch_steps = (
        (40, "Reader-directed submessages", ("DATA, DATA_FRAG, HEARTBEAT, GAP",)),
        (310, "Parse destination reader EntityId", ("readerID from the submessage",)),
        (580, "Select associated readers", ("known ID: associated_readers_.find(readerID)",
                                              "UNKNOWN: visit every reader vector")),
        (850, "Build reader input", ("DATA/FRAG: transient CacheChange_t",
                                      "serializedPayload points into receive buffer")),
        (1120, "Invoke each selected BaseReader", ("process_data_msg() / process_data_frag_msg()",
                                                    "process_heartbeat_msg() / process_gap_msg()")),
    )
    writer_dispatch_steps = (
        (40, "Writer-directed feedback", ("ACKNACK or NACK_FRAG",)),
        (310, "Parse destination writer GUID", ("destination prefix + writer EntityId",)),
        (580, "Scan associated_writers_", ("std::vector<BaseWriter*>",
                                            "offer feedback in vector order")),
        (850, "Invoke each writer handler", ("process_acknack() or process_nack_frag()",
                                               "handler checks the destination GUID")),
        (1120, "Stop when a writer accepts it", ("first handler returning true ends scan",
                                                   "otherwise destination writer is unknown")),
    )
    for y, height, steps in ((2904, 78, submessage_parse_steps),
                             (3004, 88, reader_dispatch_steps),
                             (3114, 88, writer_dispatch_steps)):
        for x, title, body in steps:
            d.box(x, y, 235, height, title, body, "data")
        for start_x, end_x in ((275, 299), (545, 569), (815, 839), (1085, 1109)):
            d.path(f"M{start_x},{y + height / 2:g} L{end_x},{y + height / 2:g}")

    d.render(OUTPUT)


if __name__ == "__main__":
    render()
