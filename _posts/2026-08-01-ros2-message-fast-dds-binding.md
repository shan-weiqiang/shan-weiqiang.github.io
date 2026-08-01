---
layout: post
title:  "How ROS 2 Binds a Message Type to Fast DDS"
date:   2026-08-01 11:00:00 +0800
tags: [ros2, systems]
---

* toc
{:toc}

A ROS 2 publisher is typed at the application boundary:

```cpp
rclcpp::Publisher<MyMessage>
```

Fast DDS `DataWriter` and `DataReader`, however, are not C++ templates over `MyMessage`. They operate on opaque addresses. How, then, does Fast DDS know how to serialize a particular ROS message?

The answer is a chain of type erasure, registration, virtual dispatch, and generated callbacks:

```text
Fast DDS DataWriter/DataReader
        │ opaque pointer
        ▼
Fast DDS TopicDataType virtual interface
        ▲
        │ implemented by
ROS rmw_fastrtps TypeSupport adapter
        │ calls message-specific callbacks
        ▼
generated ROS Fast RTPS typesupport
        │
        ▼
Fast CDR
```

This article follows ROS 2 Humble's static/generated implementation, `rmw_fastrtps_cpp`. The dynamic introspection implementation, `rmw_fastrtps_dynamic_cpp`, follows a different path and is outside this article's scope.

It complements [Type Erasure IV — ROS 2 Messages](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html) and [ROS 2 Generated Message Runtime Dependencies](https://shan-weiqiang.github.io/2026/08/01/ros2-generated-message-runtime-dependencies.html).

## Two classes named `TypeSupport`

The first source of confusion is that Fast DDS and ROS's Fast DDS bridge both define classes whose short name is `TypeSupport`.

Fast DDS defines the abstract, type-erased serialization interface `TopicDataType`. Its Humble-era operations are conceptually:

```cpp
class TopicDataType
{
public:
  virtual bool serialize(void * data, SerializedPayload_t * payload) = 0;
  virtual bool deserialize(SerializedPayload_t * payload, void * data) = 0;
  virtual void * createData() = 0;
  virtual void deleteData(void * data) = 0;
};
```

The exact signatures vary across Fast DDS releases, but the design remains the same: Fast DDS sees an opaque address and delegates type-specific behavior through virtual functions.

Fast DDS also defines:

```cpp
eprosima::fastdds::dds::TypeSupport
```

This is a shared-ownership and registration wrapper around a `TopicDataType` object. It is not the abstract serialization interface itself.

ROS's Fast DDS bridge independently defines:

```cpp
rmw_fastrtps_shared_cpp::TypeSupport
```

This class derives from `eprosima::fastdds::dds::TopicDataType` and adapts Fast DDS operations to ROS-message operations:

```cpp
class TypeSupport : public eprosima::fastdds::dds::TopicDataType
{
protected:
  virtual bool serializeROSmessage(
    const void * ros_message,
    fastcdr::Cdr & cdr,
    const void * implementation) const = 0;

  virtual bool deserializeROSmessage(
    fastcdr::Cdr & cdr,
    void * ros_message,
    const void * implementation) const = 0;
};
```

The relationship is:

```text
eprosima::fastdds::dds::TopicDataType
        ▲
        │ inherits
rmw_fastrtps_shared_cpp::TypeSupport
        ▲
        │ inherits
rmw_fastrtps_cpp::TypeSupport
        ▲
        │ inherits
rmw_fastrtps_cpp::MessageTypeSupport

eprosima::fastdds::dds::TypeSupport
        └── owns the resulting TopicDataType object
```

In short:

| Class | Role |
| --- | --- |
| Fast DDS `TopicDataType` | Type-erased virtual serialization interface |
| Fast DDS `TypeSupport` | Ownership and type-registration wrapper |
| ROS `rmw_fastrtps_shared_cpp::TypeSupport` | Adapter from Fast DDS operations to ROS-message operations |
| ROS `rmw_fastrtps_cpp::MessageTypeSupport` | Static adapter bound to generated message callbacks |

## Static generated callbacks

For `rmw_fastrtps_cpp`, ROS generates Fast RTPS callbacks for every message type at build time. The callback table includes operations for:

- CDR serialization;
- CDR deserialization;
- serialized-size calculation;
- key handling;
- bounded and plain-type properties.

ROS does not generate a different C++ adapter class for every message. It uses the same uniform `rmw_fastrtps_cpp::MessageTypeSupport` class for all statically supported ROS messages. Each instance becomes message-specific by storing that message's resolved callback table:

```cpp
const message_type_support_callbacks_t * members_;
```

The original generic `rosidl_message_type_support_t` is therefore important during endpoint creation: RMW uses it to locate the concrete Fast RTPS handle and its callback table. Once resolved, the per-sample path does not restart at the generic ROSIDL dispatcher.

```text
generic ROSIDL handle
        ↓ resolve during endpoint creation
uniform rmw_fastrtps_cpp::MessageTypeSupport class
        +
generated message-specific callback table
        ↓ construct one message-bound adapter instance
rmw_fastrtps_cpp::MessageTypeSupport(callbacks)
        ↓ implements
Fast DDS TopicDataType
```

## Publisher creation: binding the type once

Publisher creation performs two related bindings:

1. ROS resolves the generic ROSIDL handle to generated Fast RTPS callbacks.
2. Fast DDS binds the DDS endpoint to the registered `TopicDataType` adapter.

The simplified flow is:

```text
rclcpp::create_publisher<MessageT>()
        ↓
rcl publisher creation
        ↓
rmw_create_publisher(generic ROSIDL typesupport handle)
        ↓
rmw_fastrtps resolves concrete Fast RTPS typesupport
        ↓
obtain message_type_support_callbacks_t
        ↓
construct rmw_fastrtps_cpp::MessageTypeSupport(callbacks)
        ↓
the object is already a Fast DDS TopicDataType through inheritance
        ↓
register it through a Fast DDS TypeSupport ownership handle
        ↓
participant registry: DDS type name → Fast DDS TypeSupport
        ↓
create Topic(topic name, DDS type name)
        ↓
create DataWriter for that Topic
```

The Humble implementation saves the resolved callback pointer in the publisher's `CustomPublisherInfo` and constructs the same `MessageTypeSupport` adapter class used for every ROS message type. The adapter instance differs only through its stored `message_type_support_callbacks_t`. Because the class derives from Fast DDS `TopicDataType`, the resulting object already implements the interface Fast DDS needs. A Fast DDS `TypeSupport` handle supplies shared ownership and registration; it does not add another message-specific adapter layer. RMW then registers the object under a DDS type name, creates or reuses the topic, and finally creates the writer.

## How a DDS endpoint retains the type

The Fast DDS participant maintains a registry:

```text
DDS type name → eprosima::fastdds::dds::TypeSupport
```

A topic records both its topic name and its type name:

```text
Topic
├── topic name
└── DDS type name
```

A writer or reader is not created independently and associated with a topic later. It is created for an existing topic or topic description. Conceptually, the Fast DDS APIs are:

```cpp
DataWriter * writer = publisher->create_datawriter(
  topic,
  writer_qos,
  listener);

DataReader * reader = subscriber->create_datareader(
  topic_description,
  reader_qos,
  listener);
```

The supplied `Topic` gives writer creation both pieces of identity it needs: the DDS topic name and the registered DDS type name. A reader is similarly created from a `TopicDescription`, normally the same `Topic`, and obtains the corresponding type information from it.

```text
DomainParticipant
    ├── registered types: type name → Fast DDS TypeSupport
    └── Topic(topic name, type name)
             │
             ├── Publisher::create_datawriter(Topic, ...)
             │       └── DataWriterImpl bound to that topic and type
             │
             └── Subscriber::create_datareader(TopicDescription, ...)
                     └── DataReaderImpl bound to that topic and type
```

During endpoint creation, Fast DDS reads the type name from the supplied topic, finds its registered type support, and retains that support in the endpoint implementation:

```text
Topic or TopicDescription supplied to endpoint creation
        ↓ provides DDS type name
participant's registered-type lookup
        ↓
Fast DDS TypeSupport
        ↓ retained together with topic information
DataWriterImpl or DataReaderImpl
```

The lookup is not normally repeated for every sample. Each write or take uses virtual dispatch through the `TopicDataType` object already stored by the endpoint.

This distinction matters:

```text
Endpoint creation:
    identify and bind the type

Each sample:
    invoke the already-bound type behavior
```

## The per-sample boundary: two different data structures

The most important distinction in the per-sample path is between ROS's `SerializedData` and Fast DDS's `SerializedPayload_t`. Their names sound similar, but they sit on opposite sides of serialization and have different jobs.

Fast DDS's Humble-era virtual interface is conceptually:

```cpp
virtual bool serialize(
  void * data,
  SerializedPayload_t * payload) = 0;

virtual bool deserialize(
  SerializedPayload_t * payload,
  void * data) = 0;
```

For the registered ROS adapter, the arguments mean:

```text
void * data
    → actually points to ROS SerializedData
    → describes this operation's source or destination

SerializedPayload_t * payload
    → Fast DDS serialized sample buffer
    → contains CDR bytes and wire-format metadata
```

The boundary can therefore be pictured as:

```text
ROS/RMW side                                  Fast DDS side

SerializedData                               SerializedPayload_t
├── representation mode                      ├── data: byte buffer
├── source/destination pointer       ⇄        ├── length: valid bytes
└── implementation pointer                   ├── max_size: capacity
                                              └── encapsulation: CDR format
```

### `SerializedData`: an operation envelope

Despite its name, `SerializedData` does not necessarily contain serialized bytes. It is an RMW operation envelope:

```text
SerializedData
├── is_cdr_buffer
│   ├── false: data points to a native ROS message
│   └── true:  data points to an existing CDR buffer or stream
├── data
│   └── source or destination for this operation
└── impl
    └── RMW-specific serialization context
```

For a normal native-message publication, Humble constructs:

```cpp
SerializedData data;
data.is_cdr_buffer = false;
data.data = const_cast<void *>(ros_message);
data.impl = info->type_support_impl_;

info->data_writer_->write(&data);
```

`DataWriter::write()` receives `&data` as an opaque `void *`. Fast DDS does not know that it points to `SerializedData`. The meaning of the pointer belongs to the registered ROS `TopicDataType` adapter.

For an already serialized publication, RMW instead sets:

```cpp
data.is_cdr_buffer = true;
data.data = &cdr_stream;
data.impl = nullptr;  // not used in this mode
```

The envelope is necessary because the same type-erased Fast DDS operation must handle both native ROS objects and pre-serialized CDR data.

### `SerializedPayload_t`: the Fast DDS sample

`SerializedPayload_t` is the actual serialized DDS sample. Fast DDS supplies it to `TopicDataType::serialize()` as the destination buffer and receives it from the transport/history path during deserialization.

It carries the information required below the language-object boundary:

- the CDR byte buffer;
- buffer capacity;
- actual serialized length;
- CDR encapsulation and endianness.

Fast DDS needs this representation to place samples in DDS history, fragment them into RTPS submessages, transmit them, retransmit them, and deliver them to readers. It exists independently of ROS.

For a native message, the ROS adapter creates a Fast CDR stream over `payload->data`. The generated callback writes message fields through that stream, after which the adapter records the resulting `payload->length` and `payload->encapsulation`.

For pre-serialized input, the adapter skips the generated callback and copies the existing CDR bytes into `payload->data`.

### Who performs serialization?

The work crosses several ownership boundaries, so saying only "RMW serializes" or "Fast DDS serializes" is incomplete:

```text
Fast DDS DataWriter
    decides that a sample must be serialized
        ↓ calls its stored virtual interface
TopicDataType::serialize(void *, SerializedPayload_t *)
        ↓ virtual dispatch selects
rmw_fastrtps ROS adapter
    unwraps SerializedData and chooses the representation path
        ↓ for a native message
generated ROS cdr_serialize callback
    knows the concrete message fields and their order
        ↓ uses
Fast CDR
    encodes fields into payload->data
        ↓
Fast DDS receives the populated SerializedPayload_t
```

Thus Fast DDS initiates and orchestrates serialization through its registered typesupport interface. The RMW adapter implements that interface for ROS representations, the generated callback supplies message-specific knowledge, and Fast CDR performs the byte encoding.

The adapter branches as follows:

```text
is_cdr_buffer == false
    ↓
Fast DDS invokes stored TopicDataType::serialize()
    ↓ virtual dispatch to ROS adapter
adapter invokes generated callback
    ↓
Fast CDR encodes ROS fields into SerializedPayload_t

is_cdr_buffer == true
    ↓
Fast DDS invokes stored TopicDataType::serialize()
    ↓ virtual dispatch to ROS adapter
adapter copies existing CDR bytes into SerializedPayload_t
```

### Why does the envelope also carry callbacks?

The endpoint retains a `TopicDataType` whose concrete object is an `rmw_fastrtps_cpp::MessageTypeSupport`. That object stores the static callback table in `members_`. Humble nevertheless also places the same callback pointer in `SerializedData::impl`.

The stored pointer and per-operation pointer are used differently:

```text
MessageTypeSupport::members_
    persistent type configuration
    maximum size, bounded/plain status, empty-message handling, type size

SerializedData::impl
    RMW-specific context passed to this serialize/deserialize operation
    static path: message_type_support_callbacks_t
```

The shared adapter forwards `impl` to the concrete ROS operation:

```cpp
serializeROSmessage(ros_message, cdr, serialized_data->impl);
```

The Humble static implementation then performs:

```cpp
auto callbacks =
  static_cast<const message_type_support_callbacks_t *>(impl);

return callbacks->cdr_serialize(ros_message, cdr);
```

Deserialization uses `cdr_deserialize` in the same way. Passing `impl` is part of the shared RMW adapter design; Fast DDS neither defines nor interprets it. In the static implementation the callback pointer is duplicated, and the code could theoretically use `members_` for each call instead. The source shows the duplication but does not document a definitive motivation for that design choice.

## Publishing one native ROS message

The complete native-message path is:

```text
rclcpp::Publisher<MessageT>::publish(message)
        ↓
rcl_publish()
        ↓
rmw_publish()
        ↓ constructs
SerializedData
├── is_cdr_buffer = false
├── data = ROS message pointer
└── impl = generated callback table
        ↓ passed as opaque void *
Fast DDS DataWriter::write()
        ↓
DataWriterImpl requests serialization
        ↓ virtual dispatch through stored TopicDataType
rmw_fastrtps_shared_cpp::TypeSupport::serialize(
    void *, SerializedPayload_t *)
        ↓ cast void * to SerializedData *
        ↓ unwrap envelope and build Fast CDR stream over payload buffer
generated cdr_serialize callback
        ↓
Fast CDR writes CDR bytes
        ↓
SerializedPayload_t receives bytes, length, and encapsulation
        ↓
Fast DDS history and RTPS transport
```

There are two distinct runtime dispatches:

1. A C++ virtual call selects the registered ROS `TopicDataType` adapter.
2. A callback-table function pointer selects the concrete message serializer.

Fast DDS drives the operation without knowing the C++ type `MessageT`.

## Publishing an already serialized message

`rmw_publish_serialized_message()` uses the same Fast DDS entry point but avoids encoding the fields again:

```text
rmw_serialized_message_t containing CDR bytes
        ↓ wrapped as a CDR stream
SerializedData
├── is_cdr_buffer = true
├── data = CDR stream pointer
└── impl = nullptr
        ↓
DataWriter::write(void *)
        ↓
stored TopicDataType::serialize()
        ↓
ROS adapter copies existing bytes
        ↓
Fast DDS SerializedPayload_t
```

The `TopicDataType` virtual call still occurs because Fast DDS always reaches the sample through its registered type interface. The generated `cdr_serialize` callback is simply unnecessary in this branch.

## Receiving one ROS message

For `rmw_take()`, RMW prepares a native-message destination envelope:

```cpp
SerializedData data;
data.is_cdr_buffer = false;
data.data = ros_message;
data.impl = info->type_support_impl_;
```

The direction across the boundary reverses:

```text
RTPS/DDS bytes arrive
        ↓
Fast DDS SerializedPayload_t
        ↓
DataReaderImpl invokes stored TopicDataType::deserialize()
        ↓ virtual dispatch
rmw_fastrtps_shared_cpp::TypeSupport::deserialize(
    SerializedPayload_t *, void *)
        ↓ cast void * to SerializedData *
        ↓ unwrap destination and create Fast CDR reader over payload bytes
generated cdr_deserialize callback
        ↓
fields are written into the destination ROS message
        ↓
rcl/rclcpp returns the populated message
```

For a serialized take, `is_cdr_buffer` selects the other branch and the adapter copies the payload bytes into the caller's serialized destination instead of invoking the message-specific deserializer.

## Where compile-time typing ends

The application-facing `rclcpp` API uses templates:

```cpp
rclcpp::Publisher<MyMessage>
rclcpp::Subscription<MyMessage>
```

Those templates provide compile-time type safety and obtain the generated ROSIDL handle for `MyMessage`. Below the RMW boundary, the important interfaces are type-erased:

The typed-to-erased transition begins with a generic function-template declaration supplied by the ROS C++ runtime:

```cpp
// rosidl_runtime_cpp/rosidl_typesupport_cpp/message_type_support.hpp
namespace rosidl_typesupport_cpp {

template<typename T>
const rosidl_message_type_support_t *
get_message_type_support_handle();

}  // namespace rosidl_typesupport_cpp
```

That declaration is not generated separately for every message. The interface package generates an explicit specialization for each concrete message type and exports it from the package's C++ typesupport library. Conceptually:

```cpp
template<>
const rosidl_message_type_support_t *
get_message_type_support_handle<MyMessage>()
{
  return /* MyMessage's generic ROSIDL handle */;
}
```

When `rclcpp::Publisher<MyMessage>` is instantiated, its template code calls this specialization. The C++ compiler checks `MyMessage` statically, while the returned value has the uniform erased type `const rosidl_message_type_support_t *` expected by `rcl` and RMW.

```text
rclcpp template instantiated with MyMessage
        ↓ direct, type-checked C++ call
generated explicit specialization:
get_message_type_support_handle<MyMessage>()
        ↓ returns uniform erased representation
generic rosidl_message_type_support_t handle
        ↓
rcl and RMW
```

The generated specialization and its companion predictable `extern "C"` symbol are explained in detail in [Type Erasure IV — C++ additional export: template specializations](https://shan-weiqiang.github.io/2026/06/13/type-erasure-part-four-ros2.html#c-additional-export-template-specializations).

```text
rclcpp template API
        ↓ calls generated explicit specialization
generic ROSIDL handle
        ↓
rcl and RMW C APIs
        ↓ passes SerializedData as an opaque pointer
Fast DDS DataWriter/DataReader
        ↓ invokes stored virtual TopicDataType
ROS adapter + generated callback + Fast CDR
        ↓ fills or reads SerializedPayload_t
        ↓ DDS history and RTPS transport
```

This is why Fast DDS writers and readers do not need to be templates over every ROS message type. The endpoint stores a polymorphic serialization object, while generated callbacks carry the concrete message behavior.

## Final mental model

The complete mechanism has two phases.

During endpoint creation:

```text
generic ROSIDL handle
        ↓ resolve once
generated Fast RTPS callbacks
        ↓
ROS TopicDataType adapter
        ↓ register by DDS type name
Fast DDS participant registry
        ↓ lookup while creating endpoint
DataWriter/DataReader retains Fast DDS TypeSupport
```

For each sample:

```text
DataWriter/DataReader
        ↓ invokes stored TopicDataType
ROS adapter
        ├── unwraps SerializedData operation envelope
        └── reads or fills Fast DDS SerializedPayload_t
                    ↓ native-message branch
        generated callback + Fast CDR
```

The core conclusions are:

1. Fast DDS `DataWriter` and `DataReader` are not message-type templates.
2. Fast DDS `TopicDataType` is the abstract type-erasure interface.
3. ROS's `rmw_fastrtps_shared_cpp::TypeSupport` adapts that interface to ROS messages.
4. Fast DDS's separately named `TypeSupport` owns and registers the adapter.
5. The generic ROSIDL handle is resolved during endpoint creation, not from scratch for every sample.
6. The writer or reader retains the registered type support and uses virtual dispatch for each operation.
7. `SerializedData` is a ROS operation envelope, not necessarily serialized bytes.
8. `SerializedPayload_t` is the actual Fast DDS serialized sample used by DDS history and RTPS transport.
9. Fast DDS initiates serialization through `TopicDataType`; the ROS adapter, generated callbacks, and Fast CDR implement it for ROS messages.
10. In Humble's static implementation, `SerializedData::impl` carries the callback pointer even though the adapter also stores it in `members_`.

In short:

> ROS 2 binds a generated message to Fast DDS once while creating the endpoint, then serializes each sample through a stored type-erased adapter and generated callback table.

## Source references

ROS 2 Humble:

- [`rmw_fastrtps` Humble source](https://github.com/ros2/rmw_fastrtps/tree/humble)
- [`rmw_fastrtps_shared_cpp::TypeSupport` and `SerializedData`](https://github.com/ros2/rmw_fastrtps/blob/humble/rmw_fastrtps_shared_cpp/include/rmw_fastrtps_shared_cpp/TypeSupport.hpp)
- [Shared adapter serialization and deserialization](https://github.com/ros2/rmw_fastrtps/blob/humble/rmw_fastrtps_shared_cpp/src/TypeSupport_impl.cpp)
- [Static publisher creation and type registration](https://github.com/ros2/rmw_fastrtps/blob/humble/rmw_fastrtps_cpp/src/publisher.cpp)
- [`rmw_publish()` and its `SerializedData` wrapper](https://github.com/ros2/rmw_fastrtps/blob/humble/rmw_fastrtps_shared_cpp/src/rmw_publish.cpp)
- [`rmw_take()` and its destination wrapper](https://github.com/ros2/rmw_fastrtps/blob/humble/rmw_fastrtps_shared_cpp/src/rmw_take.cpp)
- [Static `MessageTypeSupport`](https://github.com/ros2/rmw_fastrtps/blob/humble/rmw_fastrtps_cpp/include/rmw_fastrtps_cpp/MessageTypeSupport.hpp)
- [Static callback storage and per-call callback use](https://github.com/ros2/rmw_fastrtps/blob/humble/rmw_fastrtps_cpp/src/type_support_common.cpp)

Fast DDS:

- [`TopicDataType` abstract interface](https://github.com/eProsima/Fast-DDS/blob/v2.6.10/include/fastdds/dds/topic/TopicDataType.hpp)
- [`TypeSupport` ownership wrapper](https://github.com/eProsima/Fast-DDS/blob/v2.6.10/include/fastdds/dds/topic/TypeSupport.hpp)
- [`DataWriter` API](https://github.com/eProsima/Fast-DDS/blob/v2.6.10/include/fastdds/dds/publisher/DataWriter.hpp)
- [Writer creation and registered-type lookup](https://github.com/eProsima/Fast-DDS/blob/v2.6.10/src/cpp/fastdds/publisher/PublisherImpl.cpp)
- [Reader creation and registered-type lookup](https://github.com/eProsima/Fast-DDS/blob/v2.6.10/src/cpp/fastdds/subscriber/SubscriberImpl.cpp)
