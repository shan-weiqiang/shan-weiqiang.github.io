---
layout: post
title:  "ara::com API解析[Part 1]"
date:   2024-05-05 13:22:46 +0800
tags: [autosar]
---

标准连接：[ara::com API](https://www.autosar.org/fileadmin/standards/R23-11/AP/AUTOSAR_AP_EXP_ARAComAPI.pdf)

---
**NOTE**

以下文中用到的词语解释：

- *通信协议*，*驱动协议*： 如果不是特别说明，这里*通信协议*指的是ComAPI底层使用的通信驱动协议，例如DDS、SOME/IP。注意**不是**网络协议
- *ComAPI*, *ComAPI绑定*，*绑定层*，*绑定*，*适配层*：这些都是指ComAPI层的接口实现，也称作绑定实现；它是存在于应用层与通信协议之间的适配代码
- *Proxy*，*Proxy类*，*客户端*：如无特别说明，都是指服务的消费方，Proxy接收Skeleton提供的服务
- *Skeleton*，*Skeleton类*，*服务端*：如无特别说明，都是指服务提供方，Skeleton为Proxy提供服务
- *服务实例*，*Skeleton类实例*，*Skeleton实例*：都是指一个具体的服务实例， 它是Skeleton类的实例；服务实例全局唯一
- *消费实例*，*Proxy类实例*， *Proxy实例*：是指一个具体的消费方，它有唯一的Client ID; 注意Proxy实例是没有服务实例ID的，服务ID是Skeleton实例的唯一标识符
- Skeleton/Proxy的**实例**与Seleton/Proxy**类**是两个概念，文中如果指的是实例，则会具体写明，否则指的是Skeleton/Proxy类本身

---

* toc
{:toc}


# 3 Introduction

## 3.1 Approach

> We need a Communication Management, which is NOT bound to a concrete
network communication protocol. It has to support the SOME/IP protocol but
there has to be flexibility to exchange that.

---
**NOTE**

ComAPI应当支持多种底层通信协议。这个特征在其他API中也有支持，比如ROS API。目前AUTOSAR AP规范中提供了两种协议绑定支持：SOME/IP，DDS。在AUTOSAR的模型中，主线是按照SOME/IP规范设计的，DDS的绑定模型多数是为了跟SOME/IP的模型对称。相比SOME/IP，DDS协议对底层传输层的封装更彻底，用户无需指定具体的传输层端口号，协议等也可以按照标准的xml文件指定。服务发现方面，DDS只需要Domain ID和Topic名称即可在VLAN中通信，而SOME/IP需要通过具体的组播发现和EventGroup等概念来进行服务发现，详细可见[SOME/IP Service Discovery](https://shan-weiqiang.github.io/2024/04/08/SOME-IP-SD-%E8%A7%A3%E8%AF%BB.html), [SOME/IP](https://shan-weiqiang.github.io/2024/04/19/SOME-IP-%E8%A7%A3%E8%AF%BB.html)

---

> The AUTOSAR service model, which defines services as a collection of provided
methods, events and fields shall be supported naturally/straight forward.

---
**NOTE**

如果底层通信的驱动协议，如DDS没有这些概念，则需要在绑定的时候通过中间层支持

---

> The API shall support an event-driven and a polling model to get access to communicated data equally well. The latter one is typically needed by real-time applications to avoid unnecessary context switches, while the former one is much
more convenient for applications without real-time requirements

---
**NOTE**

Polling意味着在上层应用的线程中直接获取数据，不会阻塞线程，也不会发生线程的上下文切换；Polling模式需要底层有消息缓冲池用于存放到达的消息队列。事件驱动模式从操作系统层面大致有两种执行方式，第一种是同步执行，即由通信线程在收到消息后直接调用应用层的回调，这种方式会阻塞通信的消息接收；另一种是异步执行，通过使用任务执行线程池来处理到达的消息以及回调，这种方式不会阻塞消息的接收，但是会有线程的上下文切换。

---

> Possibility for seamless integration of end-to-end protection to fulfill ASIL requirements.


---
**NOTE**

E2E是功能安全必须的。发送端对数据的保护发生在序列化后，接收端解保护发生在反序列化前，与底层的通信协议并没有直接的关系，任何协议都可以实现E2E。

---

> Support for static (preconfigured) and dynamic (runtime) selection of service instances to communicate with.

---
**NOTE**

注意这里不是动态和静态的服务发现，而是动态和静态的选择服务实例；这通常是从Proxy实例的角度出发来说的，AUTOSAR AP的ComAPI接口中可以在FindService的时候指定具体的通信服务实例，也可以发现所有的匹配成功的服务实例，Proxy可以动态的在运行时选择与哪一个服务实例进行通信。

注意：一个Proxy实例只能与一个服务实例进行通信；如果一个Proxy类需要同时与多个服务实例通信，则必须实例化多个Proxy实例；Proxy类的FindService方法是`static`的。

---

## 3.2 API Design Visions and Guidelines

> Consequently, ara::com does not provide any kind of component model or framework, which would take care of things like component life cycle, management of program flow or simply setting up ara::com API objects according to the formal component description of the respective application.
> 
> All this could be easily built on top of the basic ara::com API and needs not be
standardized to support typical collaboration models.

---
**NOTE**

ComAPI仅仅提供了Proxy/Skeleton类的标准方法接口，不提供类的封装以及更上层SWC的封装方法；AUTOSAR文档是采用继承的方式在Proxy/Skeleton类中实现相关Service的实现，例如event handler，method handler等。实际实现中，也可以采用set handler注册回调的方式。

---

# 4 Fundamentals

## 4.1 Proxy/Skeleton Architecture

![Alt text](/assets/images/proxy_skeleton.png)

---
**NOTE**

Service Interface Definition: 服务接口的定义。这个是通过AUTOSAR的模型定义的。AUTOSAR的模型系统本质上是一种接口描述语言（IDL)，可以参照DDS的.idl文件，Google Protobuf的.proto文件，或者ROS2的.msg文件。与以上这些IDL不同，AUTOSAR的模型系统覆盖面更广泛，不仅仅是数据类型的定义，它包括了整个软件平台的硬件和软件。AUTOSAR AP可以理解为对整个平台软件，硬件的建模。AUTOSAR AP的代码引擎将AUTOSAR AP的模型编译成两部分内容：`code`和`manifest`，即代码和配置清单。模型是一种更高级层级抽象的语言，代码引擎就是这种语言的编译器。所以在这个图中，使用了`generated from`字样，其实是代码引擎的功能。

Middleware Transport Layer： 这一层指的是通信的驱动协议，可以是上面提到的SOME/IP， DDS等

Service Proxy/Skeleton: 服务的消费方和提供方。在Proxy端，类的Findservice方法是`static`的，可以通过这个类的静态方法找到多个Skeleton实例，从类的层面Proxy与Skeleton是N-N的通信模式，即一个Proxy类可以与多个Skeleton类通信，一个Skeleton类也可以与多个Proxy类通信，这些都是同时的。但是，Proxy与Skeleton不同的地方在于类的实例，在Proxy类通过静态方法找到对应的Skeleton实例后，需要动态的创建Proxy的实例，而这个Proxy实例只能与唯一的一个Skeleton的服务实例通信；而Skeleton端则不同，一个Skeleton的实例就可以实现同时与多个Proxy实例通信。在实际应用中，如果一个Proxy类需要从多个Skeleton服务实例接收服务，则需要注意应用层注册的函数方法的可重入性.

Service Consumer Implementation： Proxy一侧的应用层实现，例如在Polling模式中调用GetNewSample获取数据；在事件驱动模式中，注册的新消息到达后的回调实现等；这些实现通过标准的ComAPI接口与应用层进行连接，其实现本身并不是ComAPI的一部分。

Service Implementation：服务的应用层实现，例如应用层调用Send接口发送数据；method中注册应用层的方法实现回调等；这些实现通过标准的ComAPI接口与应用层连接，其实现本身并不是ComAPI的一部分。

一个Client或者Service应用，需要三部分的代码才能实现：

- 应用层的实现代码
- ComAPI标准接口代码及绑定实现
- 底层通信驱动协议代码

---

## 4.3 ara::com Event and Trigger based communication


![Alt text](/assets/images/event.png)

---
**NOTE**


Client/Server application: 服务的消费和提供方的应用代码；这部分是服务和消费的具体实现，代码中主要是调用ComAPI的标准接口，注册回调等。例如Send，Subscribe，method的处理函数回调，消息的时间触发回调，获取消息GetNewSample等都是在应用代码中调用的。

Proxy/Skeleton： 这部分是标准的ComAPI接口类，提供了AUTOSAR定义的标准接口API

Communication Management Middleware： 这部分是比较特殊的代码，可以认为是ComAPI与底层驱动协议的适配代码(adaptor)，它的作用在于基于底层不同的通信协议，来实现上层的ComAPI，从而使应用代码进需要使用ComAPI，而无需关系底层的通信驱动协议。这部分代码通常是跟底层通信协议一对一的，例如SOME/IP和DDS，它们分别有自己的适配代码。

Network Binding: 底层的通信协议绑定，例如SOME/IP， DDS。注意不要跟OSI的传输层混淆。

在GetNewSamples接口中，传入的是一个用户回调，Communication Management Middleware这一层需要按照顺序逐个对每一个消息调用该回调。

---


## 4.4 ara::com Method based communication

![Alt text](/assets/images/method.png)

---
**NOTE**

method的实现基于`promise`/`future`组合，功能是实现method请求端和处理端的异步。注意在请求端和处理端分别有一组`promise`/`future`组合。

在method处理端，可以有三种模式：

- kEvent： 并发的事件驱动模式；具体实现上一般是个线程池
- kEventSingleThread: 事件驱动，单线程
- Polling： 在用户的Polling方法中处理并发送

这里需要额外说明Fire&Forget的特殊情况，特别是当返回值是`void`的情形：

- 如果method是Fire&Forget，则method请求端无需等待处理端的返回；注意即便返回值类型是`void`，也需要等待处理端的返回
- 如果不是Fire&Forget，则即便返回值类型是`void`，请求端也需要等待处理端返回的信号

与event相比，method还有一个额外的特征需要管理，就是session管理。在SOME/IP协议中，这是通过Client ID来完成的，详见[Request ID](https://shan-weiqiang.github.io/2024/04/19/SOME-IP-%E8%A7%A3%E8%AF%BB.html#4124-request-id-32-bit). 在其他的协议绑定，例如DDS中，需要在通信适配层来对session进行管理。

---


## 4.8 Service Connection Approach

### 4.8.1 Instance Identifiers and Instance Specifiers

> Instance identifiers are used within ara::com, on client/proxy side, when a specific
instance of a service shall be searched for or — at the server/skeleton side — when a
specific instance of a service is created.

---
**NOTE**

Instance identifier 表示一个服务的Instance，一个服务的Instance有一个全局唯一的Instance ID。只有Skeleton实例才有，一个Skeleton类的实例可以对应一个或者多个服务实例。Proxy端是没有服务实例ID的，但需要指定一个其需要发现的服务实例D或者发现所有服务实例ID。

---

> If the unambiguousness is ensured, the integrator/deployer can assign a dedicated
technical binding with its specific instance IDs to those "instance specifier" via a "manifest file", which is specifically used for a distinct instantiation/execution of the executable.
>
> This explicitly allows, to start the same executable N times, each time with a different
manifest, which maps the same ara::core::InstanceSpecifier differently


---
**NOTE**

参考[Specification of Manifest](https://www.autosar.org/fileadmin/standards/R23-11/AP/AUTOSAR_AP_TPS_ManifestSpecification.pdf)中`ServiceInstanceToPortPrototypeMapping`。

在AUTOSAR AP的模型中一个PortPrototype是一个Service Interface在应用软件（Software Component）中的实例化，而一个Service Instance是一个Service Interface在驱动协议中的实例化。每一个应用软件的每一个PortPrototype都有一个全局唯一的模型路径，例如`/a/b/c`，而这个路径就是所谓的Instance Specifier;每一个Service Instance在模型中也有自己的全局唯一的路径，例如`/d/e/f`，这个路径就是所谓的Instance Identifier（也唯一的对应一个Instance ID）。

`ServiceInstanceToPortPrototypeMapping`的作用就是将Instance Identifier映射到Instance Specifier。且每一个Instance Specifier可以映射多个Service Identifier（multi-binding）。 这在现实中的意义是：一个SWC的一个PPort口可以通过ComAPI在底层多种通信协议下进行数据发送；一个SWC的RPort口可以同时从多个驱动协议的通道获取服务（不常见）。

同一个Instance Specifier在不同的模型配置中，都可以映射不同的Instance Identifier（但是Service Interface必须对应一致），这就是文中所说的*This explicitly allows, to start the same executable N times, each time with a different manifest, which maps the same ara::core::InstanceSpecifier differently*的含义。

Instance Identifier和Instance Specifier都是*部署*阶段的模型元素，代码引擎会根据不同的部署模型生成不同的部署配置文件清单（例如json），在配置清单中会详细的包含Instance Specifier与Instance Identifier的对应关系。这就是文中从Instance Specifier解析Instance Identifier的信息来源：解析配置清单，获取对应信息。

---



