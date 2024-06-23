---
layout: post
title:  "AUTOSAR CM: network binding [part1]"
date:   2024-06-08 9:22:46 +0800
tags: [autosar]
---

ara::com API隔离了上层应用与底层通信驱动之间的联系，让应用无需感知底层的通信协议。AUTOSAR通信管理的网络绑定层定义如何将SOME/IP，DDS协议应用于实现comAPI

参考：
- [AUTOSAR service model: a big picture](https://shan-weiqiang.github.io/2024/06/08/AUTOSAR-Service-Model-a-big-picture.html)
- [ara::com API 1](https://shan-weiqiang.github.io/2024/05/05/ara-com-API-%E8%A7%A3%E8%AF%BB-Part-1.html)
- [ara::com API 2](https://shan-weiqiang.github.io/2024/05/12/ara-com-API-%E8%A7%A3%E8%AF%BB-Part-2.html)
- [ara::com API 3](https://shan-weiqiang.github.io/2024/06/01/ara-com-API-%E8%A7%A3%E8%AF%BB-Part-3.html)
- [AUTOSAR_AP_SWS_CommunicationManagement.pdf](https://www.autosar.org/fileadmin/standards/R23-11/AP/AUTOSAR_AP_SWS_CommunicationManagement.pdf)

## 7.4 Network binding

网络绑定应支持当使用不同的底层通信协议时，用户的代码无需重新编译，只需要动态或者静态的连接:

- 用户代码应当完全与底层的通信协议无关，只通过ara::com API使用CM
- 底层通信协议部署的改变，不需要用户应用代码的重新编译，通过如下方式实现:
  - 生成不同的manifest配置清单
  - 与底层通信协议库的静态或者动态重新连接

### 7.4.1 SOME/IP Network binding

SOME/IP的绑定支持:

- 每个event或method只能指定一种传输层协议:TCP或者UDP
- event如果是UDP，则可以支持单播或者组播两种模式，且SOME/IP协议支持运行时在两种方式之间切换
- method仅支持单播

#### 7.4.1.1 Static Service Connection

SOME/IP服务链接时，允许静态指定每个event，method的连接IP，协议，端口信息：

- 这些信息在ProvidedSomeipServiceInstance和RequiredSomeipServiceInstance相关的模型中指定(最终的静态配置清单通过这些模型生成)
- 如果有静态的连接信息，SOME/IP-SD的运行时服务发现信息被忽略

---
**NOTE**

静态的通信

---
