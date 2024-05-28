---
layout: post
title:  "ara::com API 解读[Part 1]"
date:   2024-05-05 13:22:46 +0800
tags: [AUTOSAR]
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


### 5.3.6 Methods

> The operator contains all of the service methods IN-/INOUT-parameters as INparameters. That means INOUT-parameters in the abstract service method description
are split in a pair of IN and OUT parameters in the ara::com API.

---
**NOTE**

服务接口中的每一个method都对应一个实现了`()`操作符的类。`()`操作符的入参就是method的In+In/Out参数；返回值是`ara::core::Future`类型，其模板参数类型是一个封装了这个method所有的Out+In/Out类型的结构体。关于In/Out类型，AUTOSAR规定要将其分别放在入参和返回值中，而不是通过非常量引用或者指针形式传入参数，然后通过引用或者指针原地返回结果。也就是说In/Out method参数类型，只是一个语法糖，等同于分别在In,Out中分别增加一个相同类型的参数。不支持通过引用或者指针原地返回结果的原因也很简单：method的返回类型是一个`future`，且必须马上返回，而不是block等待；如果入参是一个非常量引用或者指针，则method的调用依赖于周围的环境，则必须block等待，失去了method调用的异步特性。

---

#### 5.3.6.1 One-Way aka Fire-and-Forget Methods

fire-and-forget模式返回类型为`void`，但是返回`void`的方法不一定是fire-and-forget:

- fire-and-forget method的Proxy端不会等待Skeleton端的返回结果，而是在讲数据发送到网络后直接在本地的`promise`中`set_value`
- 返回值为`void`但不是fire-and-forget的method，即便返回值是`void`，Proxy端也要在接收到Skeleton端的通知后才会讲`promise`设置值，即便这个值是`void`

#### 5.3.6.2 Event-Driven vs Polling access to method results

AUTOSAR method对事件event-driven和polling的支持是通过对[std::future](https://en.cppreference.com/w/cpp/thread/future)的扩展实现的:

- event-driven: AUTOSAR的`ara::core::Future`实现了如下接口，使`future`可以注册一个callback，当数据可用时直接异步回调

```c++
template <typename F>
auto then(F&& func) -> Future<SEE_COMMENT_ABOVE>;
```
这个callback被调用的线程可能是`then`被调用的线程；也可能是`promise`的`set_value`线程

- polling: AUTOSAR的`ara::core::Future`提供`bool is_ready() const;`，这个接口是non-blocking的，如果返回`true`，则`wait`肯定不会block

#### 5.3.6.3 Canceling Method Result

`promise/future` 是 *DefaultContructible* 和 *MoveConstructible*, 但不是*CopyConstructible* 或者 *CopyAssignable*的，所以如果想要放弃method结果，需要使用拷贝复制给`future`一个空的`ara::com::Future`，这样当`promise/future`的`shared state`就会只有`promise`的引用，当`promise`调用了`set_value`且生命周期结束后，`shared state`会自动释放。

### 5.3.7 Fields

fields是event和method的集合，可以用如下几条总结fields的特点:

- 与event不同的时，一旦Proxy订阅了一个field，Skeleton会自动发送当前的值给Proxy
- `Get()/Set()`可以用来获取或者设定当前的field值，就是普通的method

除此之外，field与event一样，也有`Subscribe`,`GetSubscriptionState`,`SetReceiveHandler`等方法。

### 5.3.8 Triggers

trigger是一个特殊的event，它没有数据，所以不需要`local cache`。除了`GetNewSamples`方法变成`size_t GetNewTriggers()`以外，其他都与event相同。

## 5.4 Skeleton Class

### 5.4.3 Instantiation (Constructors)

> Exactly for this reason the skeleton class (just like the proxy class) does neither support
copy construction nor copy assignment! Otherwise two "identical" instances would exist
for some time with the same instance identifier and routing of method calls would be
non-deterministic.

---
**NOTE**

每一个Skeleton和Proxy的*实例*都是全局唯一的，所以Skeleton和Proxy类都不是*CopyConstructible*和*CopyAssignable*的:

- Skeleton的实例通过Instance ID唯一确定，全局唯一
- Proxy通过Skeleton的Instance ID实例化，与对应的Skeleton创建链接

面对不同通信协议，binding层需要根据各个协议的特点适配，从而在ComAPI层看起来有一致的行为：

- Skeleton的实例必须是全局唯一的，且能够接收不同Proxy实例的连接，对它们提供服务
- Proxy的实例必须能够与Skeleton进行一对一的通信，且要保证event订阅能够准确发送到Proxy实例；method的response能够和request准确配对，不能出现错乱

---

Skeleton有三种类型的构造函数，分别接收：

- `ara::com::InstanceIdentifier`: 一个确定的服务Instance, 需要包含ID，底层通信协议等信息；Skeleton类可以通过它来实例化底层的通信协议
- `ara::com::InstanceIdentifierContainer`: 一组服务Instance；Skeleton会实例化其中所有的服务实例；称为multi-binding
- `ara::core::InstanceSpecifier`: 首先通过它来解析manifest，获取`ara::com::InstanceIdentifier`，然后再通过`ara::com::InstanceIdentifier`实例化Skeleton；根据manifest，也可能是multi-binding

### 5.4.4 Offering Service instance

> From this point in time, where you call it, method calls might be dispatched to your
service instance — even if the call to OfferService() has not yet returned.

在`OfferService()`内部，对外提供服务需要的系统资源，例如uds socket、共享内存、TCP/UDP监听端口，开始分配，并对外发送当前服务实例的存在；在`OfferService()`还未返回的时候，可能已经有Proxy的实例与当前Skeleton实例创建链接并发送订阅、method请求；Skeleton析构函数会间接停止对外提供服务，释放系统资源；也可以主动调用` StopOfferService()`主动停止对外提供服务。

### 5.4.5 Polling and event-driven processing modes

Skeleton端的polling和event-driven主要体现在对method请求的处理上；Proxy端的polling和event-driven主要体现在对订阅的event数据处理上。在Skeleton的构造函数中，第二个参数用于指定method请求的处理方式： kPoll, kEvent, kEventSingleThread：

- 同一个Skeleton实例，其提供的所有方法都共用同一个处理方式
- 当Skeleton实例是multi-binding时，Skeleton实例包含的所有服务实例的所有method都共用同一个处理方式
- 默认是kEvent方式

#### 5.4.5.1 Polling Mode

