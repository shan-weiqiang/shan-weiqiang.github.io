---
layout: post
title:  "ara::com API 解读[Part 2]"
date:   2024-05-05 13:22:46 +0800
tags: [AUTOSAR]
---

[ara::com API](https://www.autosar.org/fileadmin/standards/R23-11/AP/AUTOSAR_AP_EXP_ARAComAPI.pdf)是理解AUTOSAR AP中面向服务架构的入口。无论对于底层BSW开发，模型和代码引擎开发，还是对于上层应用开发，都是需要理解的。可以说ara::com API是应用层开发、BSW开发、模型/代码引擎开发的三者交汇点。理解它非常重要。本文是第二部分。

---
**WARNING**

本文不是翻译，是对原文的注解，所有信息请以原文为准。

---

* toc
{:toc}

# 5 Detailed API description

## 5.3 Proxy Class

> The Proxy class is generated from the SI description of the AUTOSAR meta model.
ara::com does standardize the interface of the generated Proxy class.
>
> The toolchain of an AP product vendor will generate a Proxy implementation class exactly implementing this interface.

---
**NOTE**

Proxy类的API接口是AUTOSAR定义好的，所有的代码引擎都需要生成符合标准要求的API。

---

### 5.3.3 Constructor and Handle Concept


> As you can see in the Listing 5.2 ara::com prescribes the Proxy class to provide a
constructor. This means, that the developer is responsible for creating a proxy instance
to communicate with a possibly remote service.

---
**NOTE**

Proxy类的特点可以总结如下：

- `static`方法用于发现服务
- 应用开发者需要通过发现的`HandleType`创建Proxy类的实例
- 每一个Proxy类的实例只能与一个Skeleton端的服务实例通信

每一个Proxy类的实例都是一个独立的Client（从Skeleton的角度看），它们都有独立的Client ID；在method调用的时候Skeleton端的服务实例通过Client ID来区分这些不同的订阅者。

---

### 5.3.4 Finding Services

通过使用StartFindService和FindService两个`static`方法来发现服务实例：

- StartFindService为异步发现，注册一个回调到COM，每当有新的服务实例被发现，回调会被调用
- FindService为同步发现，直接返回发现结果

这两个API都有两个重载，分别接收` ara::com::InstanceIdentifier`和` ara::core::InstanceSpecifier`，关于这二者的区别详见[Part 1](https://shan-weiqiang.github.io/2024/05/05/ara-com-API-%E8%A7%A3%E8%AF%BB-Part-1.html#481-instance-identifiers-and-instance-specifiers)

#### 5.3.4.1 Auto Update Proxy instance

当已经被发现的服务实例由于各种原因暂停提供服务，而后又重新提供服务后，可以通过自动更新Proxy实例来继续通信，而无需重新走一遍FindService，创建Proxy实例的流程。

此外，允许在StartFindService注册的回调函数中直接使用已经存在的Proxy实例：

- 必须在调用这个回调前，做完自动Proxy实例的更新,这样才能保证Proxy实例的可用性

以上自动更新是通过底层的服务发现模块提供的状态来完成的.

---
**NOTE**

笔者对这个功能持保留意见：

1. 为什么会允许出现在运行时Proxy实例更新的情况？按照文中所说，Proxy实例甚至允许出现底层传输层地址改变的情况,这严重违反了AUTOSAR部署的意义：既然已经是部署，就不能允许在运行时更新部署配置信息。这显然是自相矛盾的。
2. 即便在调用StartFindService注册的回调前自动更新了已经存在的Proxy实例，那也不能保证在调用这个实例的API时对方的服务实例仍然有效。因为这中间存在时间差，而对方服务实例可能远在另外一台机器。

综合以上两点，自动更新Proxy服务实例的功能显得有点过度设计了。

---

### 5.3.5 Events

#### 5.3.5.1 Event Subscription and Local Cache


如果Proxy端想要接收服务实例中的一个event，则必须使用event订阅这个接口。这个接口有两个作用：

- 告诉COM模块需要接收这个event的数据
- 告诉COM模块需要在ComAPI层开辟多少存储空间用于存放数据

---
**NOTE**

`ara::core::Result<void> Subscribe(size_t maxSampleCount);` 对于这个接口有必要进一步的说明和解释：

- `maxSampleCount`表示当前Proxy需要为当前event开辟的存放缓存数据的池子大小，这个池子与底层的协议绑定完全无关，比如DDS和SOME/IP，它不是底层协议的缓存，而是ComAPI binding层的缓存
- 在`GetNewSamples`接口中需要将底层通信协议，例如DDS和SOME/IP，中的数据直接解序列化到这个池子，然后将指向这个池子中数据的指针`SamplePtr`传给上层应用；`SamplePtr`的行为将在后续小结详细说明

---

#### 5.3.5.3 Accessing Event Data — aka Samples

> So there has to be taken an explicit action, to get/fetch those event samples from those buffers,eventually deserialze it and and then put them into the event wrapper class instance
specific cache in form of a correct SampleType. The API to trigger this action is
`GetNewSamples()`.

---
**NOTE**

这段话给出了这个获取数据接口的两个核心行为：

1. 从绑定协议的底层，例如DDS的history，中获取**未序列化**的数据流。注意这些数据流可能存储在底层绑定协议的缓存中，也可能在内核空间中，例如在IPC socket、shared memory中。这些数据通常是从本地IPC，例如UDS socket，或者UDP/TCP socket中获取的原始数据包,尚未完成反序列化。
2. 将原始字节流**反序列化**，然后存储在ComAPI的本地缓存中，即上面所说的`local cache`中，其大小在`Subscribe(size_t maxSampleCount)`时，由应用告诉ComAPI; 注意，为了保证运行时的确定性，这个池子的内存应当是固定的，不能在运行时重新申请、释放。另外，为了减少Copy，根据底层绑定协议的能力，应当尽量直接将数据反序列化到池子中，而不是先反序列化，然后Copy。

---

> On a call to GetNewSamples(), the ara::com implementation checks first, whether
the number of event samples held by the application already exceeds the maximum
number, which it had committed in the previous call to Subscribe(). If so, an
ara::Core::ErrorCode is returned. Otherwise ara::com implementation checks,
whether underlying buffers contain a new event sample and — if it’s the case — deserializes it into a sample slot and then calls the application provided f with a SamplePtr
pointing to this new event sample. This processing (checking for further samples in the
buffer and calling back the application provided callback f) is repeated until either:
> 
> - there aren’t any new samples in the buffers
> - there are further samples in the buffers, but the application provided maxNumberOfSamples argument in call to GetNewSamples() has been reached.
> - there are further samples in the buffers, but the application already exceeds its
maxSampleCount, which it had committed in Subscribe().


---
**NOTE**

这一部分解释了，如下`GetNewSamples`接口的行为：

```cpp
template <typename F>
ara::core::Result<size_t> GetNewSamples(
F&& f,
size_t maxNumberOfSamples = std::numeric_limits<size_t>::max());
```

首先这里有三个限值要说明：

1. `maxNumberOfSamples`: `GetNewSamples`接口传入的本次希望接收的最大数据数量
2. `maxSampleCount`: `local cache`本地缓存的池子大小；大小由`Subscribe(size_t maxSampleCount)`时，由上层应用指定
3. 底层绑定协议中buffer区域的可用的未读取的数据数量，姑且称为`bufferUnreadCount`

`GetNewSamples`从底层CM获取未读的、未序列化的消息，将其序列化，存储到`local cache`池子中，然后将指向这个数据的`SamplePtr`指针作为参数传递给回调函数`f`. `F`必须是`void(ara::com::SamplePtr<SampleType const>).`类型。这个过程一直循环，直到：

1. 所有CM底层的未读消息全部处理完
2. 或者，`local cache`的数量已达到`maxSampleCount`
3. 或者，本次已读取`maxNumberOfSamples`个数据

接下来说明`SamplePtr`的行为。

---

#### 5.3.5.4 Event Sample Management via SamplePtrs

这个数据类型是理解`GetNewSamples`行为和events读取数据的关键。它需要满足如下功能：

1. 它指向的内存区域应当是ComAPI实现申请的，且会被重复利用的区域；这意味着这些内存区域不会频繁的释放和申请
2. 它指向的应当是应用层可以直接使用的数据类型
3. 它指向的数据的所有权必须可以从ComAPI层`move`到应用层，且：
   1. 如有必要，为了极致的性能优化，它还应当支持引用计数，即同时将所有权给不同的应用层的Proxy
4. 最后一点也是，它与`std::unique_ptr`最大的区别：当其所有权被应用层释放，应当通知到ComAPI实现层，这样ComAPI就可以将其指向的内存区域重新利用；这里可以有两种方式：
   1. 在`SamplePtr`析构时，通过类似引用计数的方式将释放信息传递给ComAPI，这个机制可以参考`std::shared_ptr`
   2. 在`SamplePtr`中开放对应的API接口，应用程序使用完毕后，显式调用该接口

理解了以上内容后，则会有个问题，如果同一个机器上有多个Proxy订阅了另外一台机器上的同一个Skeleton服务实例，怎么样才能做到性能最优？下面来说明下这个问题。

#### 5.3.5.6 Buffering Strategies

![Alt text](/assets/images/buffer_strategie.png)

关于同机器上的订阅同一个服务实例的Proxy之间event数据共享问题，在讨论之前，必须设定一些前提，不然讨论起来就非常乱，混乱的原因大致有以下这些：

- 这个服务实例可能在当前机器，此时当Skeleton发送数据时，可能会将数据保存在：
    - kernel空间：例如uds domain socket，pipe
    - shared memory
    - daemon 进程：这是指专门用来分发的进程
- 这个服务实例可能在另外一台机器，此时当Skeleton发送数据，可能会将数据保存在：
    - kernel空间：例如TCP/UDP socket
    - daemon进程：这个是专门用来分发的进程
- Proxy实例可能在同一个进程中，也可能在不同的进程中
- 如果服务实例在当前机器，Skeleton和Proxy在同一个进程都是有可能的

以上可以看出，Proxy和Skeleton不同的位置关系，使用的IPC技术方案，都会直接影响Proxy之间的数据共享。所以，在进一步讨论之前，必须将前提条件进行限制，我们暂且限制如下：

1. 不同的Proxy在不同的进程；做这个限制的原因是，同一个进程中收取两份相同的数据实际意义很小
2. Skeleton服务实例在同一台机器；做这个限制的原因是这种情况最终会转化为同一台机器的共享，因为数据必须先通过网络到达当前机器

有了这些限制以后，再分析下，如何实现不同Proxy之间的event数据共享：

