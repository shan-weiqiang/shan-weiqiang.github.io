---
layout: post
title:  "Life of a TCP segment"
date:   2024-05-19 10:22:46 +0800
tags: [linux-programming]
---


This article iterate the process from `write` to a TCP socket, to the `read` from a TCP socket.


| ![Alt text](/assets/images/tcp__buffering_sender.png) | 
|:--:| 
| *TCP kernel buffering, sender side* |

  1.Application process calls `write` to write bytes into TCP socket, kernel check whether there is available buffer space, **Acked(ready for writing from application)** in the diagram, to store those bytes. If yes, kernel copies all the bytes into this area, starting from **AppDataWrtPtr**. If not enough space, kernel use all of the **Acked(ready for writing from application)** space. In both scenario, `write` return the number of bytes copied.


| ![Alt text](/assets/images/tcp_protocol_stack.png) | 
|:--:| 
| *Starting a journey of protocol stack* |

  2.TCP running in kernel checks `LastByteSent - LastByteAcked`, and compares it with `min{rwnd, cwnd}`, in which `rwnd` stands for *Reciving Window* in the reciever side and `cwnd` stands for *Conjestion Window* in sender side. If it is smaller than `min{rwnd, cwnd}`, kernel consume a block of bytes, starting from **LastByteSent** onwards in the **WaitToBeSent** area, and make it a *TCP segment*. The length of the segment is decided by the MTU size in data link layer, which starnds for *maximum transmission unit*. The sum of segment and  TCP header, anbd IP header should fit into a MTU, which leads to a *maximum segment size*(MSS) that equals: `MTU - TCP header size - IP header size`. This is normally `1500 - 20 - 20 = 1460` bytes. In this diagram, the numbered `N, N+1, N+2....` stands for an individual segment.

  3.TCP running in kernel add *TCP header* in the segment and make it a *IP datagram* payload. Since the IP datagram will be routed across various endpoints, routers, it is possible that the IP datagram plus the IP header is bigger than the MTU in the data link layer. In this case, the IP datagram needs to be segmented. IP running in the kernel divides the IP datagram into seperate fragmentations, each of which is a smaller IP datagram(with a unique sequence unmber). This is the only layer that will do segmentation in the TCP/IP protocol stack.

  4.Data link layer accept IP datagram from IP layer and enclose the whole IP datagram in one *frame* and add *Frame Header* into it and switch it to destination interface. 


  5.At the reciver side, in the data link layer, it just unpack it and after checking pass it to the IP layer

  6.At the IP layer, if the IP datagram is fragmented, it will wait for all the fragmentations to arrive during a specified time duration, counted with a timer. If with this duration, all fragmentations are recieved, IP running in kernel assembles them and compose a complete IP datagram and pass it to TCP layer. If the IP datagram is not fragmented, IP layer just unpack and after checking pass it to TCP layer

| ![Alt text](/assets/images/tcp_buffering_recv.png) | 
|:--:| 
| *TCP kernel buffering at the reciever* |

  7.TCP running in the reciever side accept the TCP segment and copies it in the kernel buffer, starting from the **LastByteRcvd** and send a *ack* to the sender. Note that at the reciever side, it does not need to worry there will be no space left to store the recieved segment, because in the *ack* to the sender, it will contain the size of the `rwnd`, and sender will assure that `LastByteSent - LastByteAcked <= min{rwnd, cwnd}`. The flow control is done in sender side, not the reciever side.

In above steps, there are some notes to take:

1. Except for the TCP layer, all layer beneath are unreliable transfer

2. IP layer support segmentation because it will not know before hand which data link layer it will pass through, such as Ethernet, Wifi. It might happen that the IP datagram is bigger than the MTU. However, in new IP standards and IPv6, support for segmentation is removed.

3. Except for the TCP part, all the layers beneath are also applicable to UDP and any other protocols using IP

4. The buffering at sender or the reciver side can also applicable to unix domain socket

The whole picture:

![Alt text](/assets/images/tcp_segmentation.png)