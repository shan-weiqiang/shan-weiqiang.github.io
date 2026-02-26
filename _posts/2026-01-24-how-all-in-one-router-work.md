---
layout: post
title:  "How All-In-One Routers Work"
date:   2026-01-24 9:22:46 +0800
tags: [readings]
---

* toc
{:toc}

Virtually every connected home relies on a single compact device commonly called a **wireless router**, **home gateway**, or **all-in-one router**. This small box performs several critical networking roles simultaneously:

- **Router** — connects your home to the internet
- **Switch** — connects multiple wired devices together
- **Wireless Access Point** — provides Wi-Fi for phones, laptops, tablets, smart home devices, etc.

By combining these functions into one unit, manufacturers make home networking simple, affordable, and mostly maintenance-free. This article explains how an all-in-one router actually works while clearly introducing fundamental networking concepts that appear in its settings and behavior — especially **IP addressing**, **subnet masks**, **default gateway**, **DNS**, and **NAT**.

## Core Components of an All-in-One Router

### 1. Router (Layer 3 – IP Routing)
The router is the brain that decides where packets should go. It has two main sides:

- **WAN side** — connects to your ISP modem (cable, DSL, fiber ONT, 5G gateway, etc.) and receives a **public IPv4 address** (and usually an IPv6 prefix)
- **LAN side** — serves your home network with **private IP addresses**

Most home routers use **private IP ranges** defined by RFC 1918:

- 192.168.0.0 – 192.168.255.255
- 10.0.0.0 – 10.255.255.255
- 172.16.0.0 – 172.31.255.255

The router itself usually takes the first usable address, e.g., **192.168.1.1** or **192.168.0.1**.

### 2. Built-in Switch (Layer 2 – Ethernet Switching)
The 4–8 Ethernet LAN ports you see on the back are actually a small **Ethernet switch**.  
A switch learns the **MAC addresses** of connected devices and forwards frames directly between devices on the same local network without sending traffic to the router CPU unnecessarily. This makes local file transfers, casting to TVs, printer sharing, and NAS access very fast.

### 3. Wireless Access Point (Layer 2 – Wi-Fi Bridge)
The Wi-Fi radios (2.4 GHz + 5 GHz) act as a wireless access point.  
They:

- Broadcast SSID(s)
- Perform WPA2/WPA3 authentication
- Bridge wireless clients into the same Layer 2 network as the wired devices

Once associated, a Wi-Fi device is treated just like a wired device by the switch and router.

## How Data Flows – A Practical Example

### Two directly connected computers

Imagine two computers connected directly via an Ethernet cable (or through a simple switch). Computer A (192.168.1.10) wants to send data to Computer B (192.168.1.20).

**Step 1: IP Configuration (DHCP or Manual)**
- Both computers need IP addresses. They can be:
  - Manually configured (static IPs)
  - Automatically obtained via DHCP (if a DHCP server is present)

**Step 2: ARP Resolution**
- Computer A knows the destination IP (192.168.1.20) but needs the MAC address
- Computer A broadcasts an **ARP request**: "Who has IP 192.168.1.20? Tell 192.168.1.10"
- Computer B receives the ARP request, recognizes its own IP, and replies: "192.168.1.20 is at MAC address AA:BB:CC:DD:EE:FF"
- Computer A stores this mapping in its **ARP cache** for future use

**Step 3: Data Transmission**
- Computer A now has both IP (192.168.1.20) and MAC (AA:BB:CC:DD:EE:FF)
- Computer A encapsulates the data:
  - Application data → TCP/UDP segment → IP packet (source: 192.168.1.10, dest: 192.168.1.20) → Ethernet frame (source: A's MAC, dest: B's MAC)
- The Ethernet frame is sent over the wire
- Computer B receives the frame, checks the destination MAC matches, extracts the IP packet, and delivers to the application

**Key Points:**
- No router needed for same-subnet communication
- ARP bridges Layer 3 (IP) to Layer 2 (MAC)
- The switch (if present) uses MAC addresses to forward frames

### Local communication (same subnet)
Your phone (192.168.1.55) wants to cast a video to your smart TV (192.168.1.108).

1. Phone sends an ARP request: “Who has 192.168.1.108?”
2. TV replies with its MAC address
3. Phone sends frames directly to TV’s MAC address
4. The **built-in switch** forwards them — traffic never reaches the router CPU

### Internet communication
Your laptop (192.168.1.42) opens a browser and types “https://example.com”

1. Laptop performs **DNS query** (explained below) → resolves to public IP 93.184.216.34
2. Laptop wants to send to 93.184.216.34 → realizes it’s not on 192.168.1.0/24 → sends packet to **default gateway** 192.168.1.1
3. Router receives packet, applies **NAT** (explained below), changes source IP to its public WAN IP and records the mapping
4. Packet goes out to the internet
5. Reply comes back to router’s public IP → router uses the NAT table to send it to 192.168.1.42

## Key Networking Concepts Explained

### Subnet Mask & Subnetting

The **subnet mask** tells devices which part of the IP address is the **network portion** and which is the **host portion**.

Common home values:

| Dotted decimal   | CIDR   | Usable hosts   | Binary mask                      |
|------------------|--------|----------------|----------------------------------|
| 255.255.255.0    | /24    | 254            | 11111111.11111111.11111111.00000000 |
| 255.255.254.0    | /23    | 510            | 11111111.11111111.11111110.00000000 |
| 255.255.255.252  | /30    | 2              | (used on point-to-point links)   |

Example:  
IP = 192.168.1.100  
Mask = 255.255.255.0 (/24)  
→ Network = 192.168.1.0  
→ Broadcast = 192.168.1.255  
→ Usable range = 192.168.1.1 – 192.168.1.254

Devices use the mask + their own IP to decide: “Is this destination on my local network, or do I need to send it to the gateway?”

### Default Gateway

The **default gateway** (also called default route) is simply the IP address of the router on your LAN — usually 192.168.1.1 or 192.168.0.1.

Any time a device wants to reach an IP address **outside its own subnet**, it sends the packet to the default gateway and lets the router handle the rest.

### DHCP – Dynamic Host Configuration Protocol

**DHCP** automatically assigns IP addresses and network configuration to devices when they connect to the network. Without DHCP, you'd have to manually configure IP address, subnet mask, default gateway, and DNS servers on every device.

**How DHCP Works (4-step process):**

1. **DHCP Discover** — A new device (e.g., your laptop) connects and broadcasts: "I need an IP address!"
2. **DHCP Offer** — The router's DHCP server responds: "I can give you 192.168.1.50, with subnet mask 255.255.255.0, gateway 192.168.1.1, and DNS 1.1.1.1"
3. **DHCP Request** — The device accepts: "Yes, I'll take 192.168.1.50"
4. **DHCP Ack** — The server confirms: "192.168.1.50 is yours for the next 24 hours (lease time)"

**Key Features:**
- **Lease time** — IP addresses are "rented" for a period (typically 24 hours). Devices renew automatically before expiration
- **DHCP pool** — Router reserves a range (e.g., 192.168.1.100–192.168.1.200) for dynamic assignment
- **Static reservations** — You can reserve specific IPs for devices (e.g., always give printer 192.168.1.10)
- **Centralized management** — Change DNS servers or gateway in one place (router), all devices get updated on next renewal

Most home routers run a DHCP server by default, making network setup plug-and-play.

### ARP – Address Resolution Protocol

**ARP** bridges the gap between Layer 3 (IP addresses) and Layer 2 (MAC addresses). When a device knows an IP address but needs to send an Ethernet frame, it must first discover the corresponding MAC address.

**How ARP Works:**

1. **ARP Request (Broadcast)**
   - Device A wants to send to IP 192.168.1.20
   - Device A checks its **ARP cache** (local table of IP→MAC mappings)
   - If not found, Device A broadcasts: "Who has 192.168.1.20? Tell 192.168.1.10"
   - This broadcast goes to all devices on the local network (Layer 2 broadcast)

2. **ARP Reply (Unicast)**
   - Device B (192.168.1.20) receives the request, recognizes its own IP
   - Device B replies directly to Device A: "192.168.1.20 is at MAC address AA:BB:CC:DD:EE:FF"
   - Device A stores this mapping in its ARP cache (typically for 2–4 minutes)

3. **Subsequent Communication**
   - Future packets to 192.168.1.20 use the cached MAC address
   - No ARP request needed until the cache entry expires

**ARP Cache:**
- View on Linux/Mac: `arp -a` or `ip neigh show`
- View on Windows: `arp -a`
- Entries expire after a few minutes to handle cases where devices change IPs or disconnect

**Important Notes:**
- ARP only works on **local networks** (same subnet). For remote IPs, ARP is used to find the gateway's MAC address
- ARP is a Layer 2/3 protocol — it uses IP addresses but operates at the Ethernet level
- **ARP spoofing** attacks exploit ARP's trust-based nature (devices accept ARP replies without verification)

IP (Layer 3) determines the direction of a packet by consulting the routing table to decide the next-hop IP address. If the destination is in the same subnet, the next hop is the destination itself; if it is in another network, the next hop is the default gateway. ARP then resolves that next-hop IP address into a MAC address by broadcasting a request inside the local Layer 2 network and caching the reply. Routing decides where to go; ARP discovers how to reach that next hop at Layer 2.

Once the next-hop MAC address is known, the IP packet is encapsulated into an Ethernet frame for delivery. The source and destination IP addresses remain constant end-to-end (unless modified by NAT), but the MAC addresses change at every hop. This reflects the core principle: IP provides end-to-end logical identity, while MAC addresses provide hop-by-hop physical delivery.

A Layer 2 switch forwards frames purely based on MAC addresses. It learns source MAC-to-port mappings dynamically and stores them in a MAC table. If the destination MAC is known, it forwards the frame only to the corresponding port; if unknown or broadcast, it floods the frame to all ports except the ingress port. Multiple switches connected together form one larger Layer 2 broadcast domain, extending this MAC-learning and forwarding behavior across the entire network.



### DNS – Domain Name System

DNS translates names → IP addresses.

Typical flow in a home:

1. Device asks the router (192.168.1.1) for www.netflix.com
2. Router either:
   - Answers from its DNS cache, or
   - Forwards the query to the ISP's DNS servers or public resolvers (1.1.1.1, 8.8.8.8, 9.9.9.9…)
3. Receives answer → caches it → gives IP to the client

Many modern routers support **encrypted DNS** (DoH / DoT) for better privacy.

### NAT – Network Address Translation

Because there aren’t enough public IPv4 addresses, almost every home shares **one public IP** among all devices using **NAT**.

Most common type: **PAT** (Port Address Translation)

- Laptop 192.168.1.10:port 50000 → wants google.com
- Router changes source to: public.IP:port 32001
- Records in NAT table: 192.168.1.10:50000 ↔ public.IP:32001
- Reply arrives at public.IP:32001 → router looks up table → forwards to laptop

This allows dozens of devices to use the internet through a single public IP while providing a basic layer of protection (no direct inbound connections unless port forwarding is configured).

## Summary Table – Where Each Concept Lives

| Concept           | OSI Layer | Device / Component       | Typical Home Value             | Main Purpose                              |
|-------------------|-----------|---------------------------|--------------------------------|-------------------------------------------|
| MAC address       | 2         | Switch / Access Point     | burned-in hardware address     | local device-to-device delivery           |
| IP address        | 3         | Router (LAN side)         | 192.168.x.x                    | logical addressing                        |
| Subnet mask       | 3         | Every device              | 255.255.255.0 (/24)            | determine local vs. remote                |
| Default gateway   | 3         | Every device              | 192.168.1.1                    | where to send non-local traffic           |
| DHCP              | 3–7       | Router (DHCP server)      | automatic IP assignment        | automatic network configuration           |
| ARP               | 2–3       | Every device              | IP → MAC address mapping       | resolve IP addresses to MAC addresses     |
| DNS resolver      | 5–7       | Router (forwarding)       | 1.1.1.1, 8.8.8.8, ISP DNS      | name → IP translation                     |
| NAT / PAT         | 3–4       | Router (WAN ↔ LAN)        | dynamic port mapping           | share 1 public IP among many devices      |
