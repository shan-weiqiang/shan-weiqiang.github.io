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
    d = Diagram(1962, "Fast DDS transport, resource, channel, and backing relationships")

    d.group(20, 52, 1360, 135, "PARTICIPANT")
    d.group(20, 212, 1360, 170, "PARTICIPANT-OWNED NETWORK OBJECTS")
    d.group(20, 407, 1360, 165, "COMMON ABSTRACTIONS")
    d.group(10, 582, 1380, 435, "RECEIVER SETUP FOR ONE ENDPOINT")
    d.group(25, 612, 1350, 270, "PHASE 1 — CREATE OR REUSE RECEIVE REGISTRATIONS")
    d.group(25, 897, 1350, 105, "PHASE 2 — ASSOCIATE ENDPOINT WITH MATCHING CONTROL BLOCKS")
    d.group(20, 1027, 1360, 125, "INCOMING DATA AND ENDPOINT DISPATCH")
    d.group(20, 1177, 435, 760, "UDP")
    d.group(480, 1177, 435, 760, "TCP")
    d.group(940, 1177, 435, 760, "SHARED MEMORY")

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

    registration_steps = (
        (40, "createReceiverResources()", ("scope: current Endpoint* pend",
                                            "call with unicastLocatorList,",
                                            "then multicastLocatorList")),
        (310, "for each locator in input_list", ("first pass over this list",)),
        (580, "BuildReceiverResources(locator)", ("NetworkFactory handles this locator",)),
        (850, "for each registered transport", ("transport in mRegisteredTransports",
                                                  "one decision per transport instance")),
        (1120, "Per-transport decision", ("unsupported: skip",
                                           "open: reuse; return no resource",
                                           "missing: follow creation row")),
    )
    for x, title, body in registration_steps:
        d.box(x, 642, 235, 92, title, body, "process")
    for start_x, end_x in ((275, 299), (545, 569), (815, 839)):
        d.path(f"M{start_x},688 L{end_x},688")
    d.path("M1085,688 L1109,688")

    channel_creation_steps = (
        (40, "Missing registration path", ("IsInputChannelOpen(locator) is false",)),
        (310, "ReceiverResource constructor", ("captures this transport and locator",)),
        (580, "OpenInputChannel(locator, this)", ("passes this TransportReceiverInterface*",)),
        (850, "Create/register input backing", ("UDP: get_binding_interfaces_list()",
                                                  "for each entry: socket + UDPChannelResource",
                                                  "TCP: register receiver_resources_[logical port]",
                                                  "TCP acceptors/interfaces: transport initialization",
                                                  "SHM: 1 SharedMemChannelResource")),
        (1120, "Complete new control block", ("return new ReceiverResource",
                                               "create ReceiverControlBlock + MessageReceiver",
                                               "RegisterReceiver(MessageReceiver*)")),
    )
    for x, title, body in channel_creation_steps:
        d.box(x, 767, 235, 104, title, body, "process")
    for start_x, end_x in ((275, 299), (545, 569), (815, 839), (1085, 1109)):
        d.path(f"M{start_x},819 L{end_x},819")
    d.path("M1238,739 C1238,752 158,752 158,756", "missing", 700, 749,
           marker_end="arrow")

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
        d.box(x, 927, 235, 72, title, body, "data")
    for start_x, end_x in ((275, 299), (545, 569), (815, 839), (1085, 1109)):
        d.path(f"M{start_x},963 L{end_x},963")

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
        d.box(x, 1062, 235, 70, title, body, "data")
    for start_x, end_x in ((275, 299), (545, 569), (815, 839), (1085, 1109)):
        d.path(f"M{start_x},1097 L{end_x},1097")

    columns = (
        {
            "x": 40,
            "sender": ("UDPSenderResource", ("eProsimaUDPSocket socket_", "bool only_multicast_purpose_",
                                             "bool whitelisted_", "UDPTransportInterface& transport_")),
            "transport": ("UDPTransportInterface", ("std::map<uint16_t, std::vector<UDPChannelResource*>>",
                                                      "mInputSockets", "int32_t transport_kind_ (inherited)")),
            "channel": ("UDPChannelResource", ("TransportReceiverInterface* message_receiver_",
                                                "eProsimaUDPSocket socket_", "std::string interface_",
                                                "UDPTransportInterface* transport_")),
            "backing": ("UDP mapping", ("mInputSockets[physical port] → 1..* UDPChannelResource",
                                         "UDPChannelResource::socket_ → exactly 1 socket",
                                         "all channel resources store the same callback")),
            "cardinality": ("logical output channel: 1", "direct ChannelResource refs: 0", "Receiver → channels: 1..*", "channel → input socket: 1"),
            "labels": ("delegates", "owns by port", "backs", "counts"),
        },
        {
            "x": 500,
            "sender": ("TCPSenderResource", ("Locator_t locator_", "std::weak_ptr<TCPChannelResource> channel_",
                                             "send_lambda_ captures TCPTransportInterface&")),
            "transport": ("TCPTransportInterface", ("channel_resources_: keyed by physical Locator",
                                                      "receiver_resources_: keyed by logical port",
                                                      "acceptors_: keyed by Locator")),
            "channel": ("TCPChannelResource", ("TCPTransportInterface* parent_", "Locator locator_",
                                                "std::vector<uint16_t> logical_output_ports_",
                                                "std::atomic<eConnectionStatus> connection_status_")),
            "backing": ("TCP mapping", ("TCPChannelResourceBasic::socket_",
                                         "std::shared_ptr<asio::ip::tcp::socket>",
                                         "receiver_resources_[logical port] → callback")),
            "cardinality": ("Sender → connection: 0..1 weak", "Receiver → connections: 0..*", "connection → Receivers: 0..*", "connected channel → socket: 1"),
            "labels": ("delegates", "retains", "send + receive", "counts"),
        },
        {
            "x": 960,
            "sender": ("SharedMemSenderResource", ("no concrete data members",
                                                    "send_lambda_ captures SharedMemTransport&",
                                                    "clean_up captures no object")),
            "transport": ("SharedMemTransport", ("std::vector<SharedMemChannelResource*> input_channels_",
                                                   "std::map<uint32_t, std::shared_ptr<SharedMemManager::Port>> opened_ports_",
                                                   "std::shared_ptr<SharedMemManager::Segment> shared_mem_segment_")),
            "channel": ("SharedMemChannelResource", ("TransportReceiverInterface* message_receiver_",
                                                      "std::shared_ptr<SharedMemManager::Listener> listener_",
                                                      "Locator locator_")),
            "backing": ("Shared-memory mapping", ("input_channels_ → 0..* SharedMemChannelResource",
                                                   "opened_ports_[port] → SharedMemManager::Port",
                                                   "shared_mem_segment_ is transport-wide")),
            "cardinality": ("logical output path: 1", "direct ChannelResource refs: 0", "Receiver maps to channel: 1", "channel → listener / port: 1"),
            "labels": ("delegates", "owns", "backs", "counts"),
        },
    )

    for column in columns:
        x = column["x"]
        d.box(x, 1212, 395, 100, *column["sender"], semantic="primary")
        d.box(x, 1342, 395, 128, *column["transport"], semantic="primary")
        d.box(x, 1500, 395, 114, *column["channel"], semantic="data")
        d.box(x, 1644, 395, 100, *column["backing"], semantic="neutral")
        d.box(x, 1774, 395, 128, "Cardinality", column["cardinality"], semantic="process")

        center = x + 197.5
        label_x = center + 12
        first, second, third, fourth = column["labels"]
        d.path(f"M{center},1317 L{center},1331", first, label_x, 1328,
               dashed=True, label_anchor="start")
        d.path(f"M{center},1475 L{center},1489", second, label_x, 1486,
               marker_start="diamond-filled", label_anchor="start")
        d.path(f"M{center},1619 L{center},1633", third, label_x, 1630,
               marker_start="diamond-filled", label_anchor="start")
        d.path(f"M{center},1749 L{center},1763", fourth, label_x, 1760,
               dashed=True, label_anchor="start")

    d.render(OUTPUT)


if __name__ == "__main__":
    render()
