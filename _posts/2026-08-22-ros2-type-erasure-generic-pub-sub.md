---
layout: post
title:  "ROS 2 Type Erasure with Generic Pub/Sub"
date:   2026-08-22 09:00:00 +0800
tags: [ros2, type-erasure, serialization, middleware]
---

ROS 2 provides both compile-time typed and runtime-typed publisher and
subscriber APIs. This article explains how those APIs differ, what
`type_name` controls, how serialized-message adapters work, and how arbitrary
payloads such as Protobuf should be transported safely.

The central distinction is:

> A generic ROS 2 endpoint is runtime-typed and pre-serialized. It is not an
> untyped arbitrary-byte endpoint.

* toc
{:toc}

## Typed ROS 2 publishers and subscribers

A normal publisher knows its message type at C++ compile time:

```cpp
auto publisher = node->create_publisher<geometry_msgs::msg::Twist>(
    "/cmd_vel", rclcpp::QoS(10));

geometry_msgs::msg::Twist message;
message.linear.x = 1.0;
publisher->publish(message);
```

`Publisher<T>` obtains the generated type support for `T`. ROS serializes the
C++ object before passing the resulting bytes to RMW/DDS.

A typed subscriber reverses this operation:

```cpp
auto subscription = node->create_subscription<geometry_msgs::msg::Twist>(
    "/cmd_vel",
    rclcpp::QoS(10),
    [](geometry_msgs::msg::Twist::ConstSharedPtr message) {
        useVelocity(message->linear.x);
    });
```

ROS receives the serialized sample, deserializes it as `Twist`, and invokes
the callback with a typed C++ object.

## Generic ROS 2 publishers and subscribers

A generic endpoint moves type selection from compile time to runtime:

```cpp
auto publisher = node->create_generic_publisher(
    "/cmd_vel",
    "geometry_msgs/msg/Twist",
    rclcpp::QoS(10));
```

ROS uses the runtime type name to load the installed ROSIDL type-support
library and create a typed RMW/DDS writer. The generic publisher itself does
not accept an arbitrary `void*` message or infer its C++ type. Its normal
publishing API accepts an already serialized ROS message:

```cpp
void rclcpp::GenericPublisher::publish(
    const rclcpp::SerializedMessage& message);
```

For example:

```cpp
geometry_msgs::msg::Twist message;
message.linear.x = 1.0;

rclcpp::Serialization<geometry_msgs::msg::Twist> serializer;
rclcpp::SerializedMessage serialized;
serializer.serialize_message(&message, &serialized);

publisher->publish(serialized);
```

A generic subscription receives the serialized form:

```cpp
auto subscription = node->create_generic_subscription(
    "/cmd_vel",
    "geometry_msgs/msg/Twist",
    rclcpp::QoS(10),
    [](std::shared_ptr<rclcpp::SerializedMessage> serialized) {
        geometry_msgs::msg::Twist message;
        rclcpp::Serialization<geometry_msgs::msg::Twist> serializer;
        serializer.deserialize_message(serialized.get(), &message);
        useVelocity(message.linear.x);
    });
```

## Type erasure and why generic APIs are useful

The generic API erases the compile-time C++ message type while retaining the
ROS/DDS type at runtime:

```text
Typed endpoint:
  Publisher<T>
  -> publish(const T&)

Generic endpoint:
  GenericPublisher
  -> runtime type_name
  -> publish(const SerializedMessage&)
```

The erased information is the concrete C++ object type. The information that
remains includes the ROS type name, dynamically loaded type-support handle,
topic identity, QoS, and serialized wire representation.

A final semantic consumer usually must decode the message using the correct
type. The advantage is that intermediate infrastructure does not need to
decode it at all.

### Type-independent relays

A relay can forward any installed ROS message type without including its
generated C++ header:

```cpp
struct GenericRelay
{
    rclcpp::GenericPublisher::SharedPtr publisher;
    rclcpp::GenericSubscription::SharedPtr subscription;
};

GenericRelay createRelay(
    rclcpp::Node& node,
    const std::string& input_topic,
    const std::string& output_topic,
    const std::string& type_name,
    const rclcpp::QoS& qos)
{
    GenericRelay relay;

    relay.publisher = node.create_generic_publisher(
        output_topic, type_name, qos);

    auto publisher = relay.publisher;
    relay.subscription = node.create_generic_subscription(
        input_topic,
        type_name,
        qos,
        [publisher](
            std::shared_ptr<rclcpp::SerializedMessage> message) {
            publisher->publish(*message);
        });

    return relay;
}
```

The same implementation can relay `String`, `Twist`, `Image`, `Odometry`, or
a newly installed custom type. It does not need a template instantiation,
header dependency, or dispatch branch for every message type.

### Recording and replay

Rosbag is the canonical use case. Recording needs only:

```text
topic name
runtime ROS type name
QoS metadata
serialized bytes
```

Replay reads the recorded type name, creates a generic publisher, and
republishes the stored serialized samples. Neither operation needs to
construct the corresponding C++ message object.

### Bridges, routers, and observability tools

The same type-erased boundary is useful for:

- Network and middleware bridges.
- Topic routers and proxies.
- Logging and archival systems.
- Latency and bandwidth measurement.
- Gateways that preserve ROS samples.
- Tools that copy messages without interpreting their fields.

These components remain decoupled from application message packages and do
not need recompilation every time a new message type is introduced.

### When field access is required

A component that needs semantic fields has two choices:

1. Use the correct compile-time type and `rclcpp::Serialization<T>`.
2. Load introspection or dynamic type support and decode fields at runtime.

This produces a useful architectural separation:

```text
Semantic producers and consumers
  -> typed C++ messages

Transport, relay, record, and replay infrastructure
  -> runtime type name plus SerializedMessage

Runtime inspection tools
  -> SerializedMessage plus introspection metadata
```

Type erasure therefore does not eliminate types. It postpones typed decoding
until a component actually needs message semantics.

### Practical API selection

Generic pub/sub is mainly an infrastructure API. It is most valuable when a
framework or tool must support message types selected at runtime and should
not depend directly on every generated ROS message package.

Ordinary application code usually knows its message type and needs semantic
fields. In that situation, the typed API is clearer:

```cpp
auto subscription =
    node->create_subscription<geometry_msgs::msg::Twist>(
        "/cmd_vel",
        qos,
        [](geometry_msgs::msg::Twist::ConstSharedPtr message) {
            useVelocity(message->linear.x);
        });
```

Using a generic subscription and immediately decoding into the same known C++
type adds an unnecessary layer:

```cpp
auto subscription = node->create_generic_subscription(
    "/cmd_vel",
    "geometry_msgs/msg/Twist",
    qos,
    [](std::shared_ptr<rclcpp::SerializedMessage> serialized) {
        geometry_msgs::msg::Twist message;
        rclcpp::Serialization<geometry_msgs::msg::Twist> serializer;
        serializer.deserialize_message(serialized.get(), &message);
        useVelocity(message.linear.x);
    });
```

The generic version still includes and links the `Twist` message package,
still requires `Twist` type support, manually performs work already provided
by the typed subscription, and introduces a possible mismatch between the
runtime type name and the C++ decoder type. It normally provides no advantage
for business logic that already knows the type.

A practical decision rule is:

```text
Known type + semantic field access
  -> typed Publisher<T> and Subscription<T>

Runtime-selected type + transport or storage only
  -> GenericPublisher and GenericSubscription

Runtime-selected type + semantic field access
  -> generic endpoints plus introspection or dynamic decoding
```

Exceptions exist, such as applications that load message-processing plugins
at runtime. The general rule remains that once code already knows `T` and
needs `T`, receiving a `SerializedMessage` only to decode it immediately is
unnecessary.

### Detailed example: runtime field rules with Humble APIs

Consider a monitoring framework configured with a rule rather than a compiled
message callback:

```yaml
topic: /battery_state
field: percentage
operator: less_than
threshold: 0.15
```

The framework is compiled without including
`sensor_msgs/msg/battery_state.hpp`. At startup it asks the ROS graph for the
topic's runtime type name. The serialized CDR payload is not self-describing;
the type name and its installed type support supply the missing schema.

The example below uses APIs available in ROS 2 Humble. It handles a scalar
`float32` field such as `BatteryState.percentage` and shows the complete
lifecycle: dynamic-library loading, type-support lookup, allocation,
initialization, deserialization, field lookup, value access, finalization, and
release.

```cpp
#include <rclcpp/rclcpp.hpp>
#include <rclcpp/serialization.hpp>
#include <rclcpp/typesupport_helpers.hpp>

#include <rosidl_runtime_cpp/message_initialization.hpp>
#include <rosidl_typesupport_introspection_cpp/field_types.hpp>
#include <rosidl_typesupport_introspection_cpp/message_introspection.hpp>

#include <rcpputils/shared_library.hpp>

#include <cstdint>
#include <cstring>
#include <memory>
#include <new>
#include <stdexcept>
#include <string>
#include <utility>

using MessageMember =
    rosidl_typesupport_introspection_cpp::MessageMember;
using MessageMembers =
    rosidl_typesupport_introspection_cpp::MessageMembers;

class InitializedMessage
{
public:
    explicit InitializedMessage(const MessageMembers* members)
        : members_(members),
          storage_(::operator new(members_->size_of_))
    {
        try {
            members_->init_function(
                storage_,
                rosidl_runtime_cpp::MessageInitialization::ALL);
        } catch (...) {
            ::operator delete(storage_);
            storage_ = nullptr;
            throw;
        }
    }

    ~InitializedMessage()
    {
        if (storage_ != nullptr) {
            members_->fini_function(storage_);
            ::operator delete(storage_);
        }
    }

    InitializedMessage(const InitializedMessage&) = delete;
    InitializedMessage& operator=(const InitializedMessage&) = delete;
    InitializedMessage(InitializedMessage&&) = delete;
    InitializedMessage& operator=(InitializedMessage&&) = delete;

    void* data() noexcept
    {
        return storage_;
    }

private:
    const MessageMembers* members_;
    void* storage_;
};

class RuntimeFloatRule
{
public:
    RuntimeFloatRule(
        rclcpp::Node& node,
        std::string topic,
        std::string field,
        float threshold)
        : node_(node),
          topic_(std::move(topic)),
          field_(std::move(field)),
          threshold_(threshold)
    {
        const auto topics = node_.get_topic_names_and_types();
        const auto topic_it = topics.find(topic_);
        if (topic_it == topics.end() || topic_it->second.size() != 1U) {
            throw std::runtime_error(
                "topic must exist with exactly one ROS type");
        }
        type_name_ = topic_it->second.front();

        // Used by SerializationBase to call the active RMW serializer.
        rmw_library_ = rclcpp::get_typesupport_library(
            type_name_, "rosidl_typesupport_cpp");
        rmw_type_support_ = rclcpp::get_typesupport_handle(
            type_name_, "rosidl_typesupport_cpp", *rmw_library_);

        // Used to discover message size, lifecycle functions, fields,
        // field types, nested members, and byte offsets.
        introspection_library_ = rclcpp::get_typesupport_library(
            type_name_, "rosidl_typesupport_introspection_cpp");
        const auto* introspection_handle =
            rclcpp::get_typesupport_handle(
                type_name_,
                "rosidl_typesupport_introspection_cpp",
                *introspection_library_);

        if (introspection_handle == nullptr ||
            introspection_handle->data == nullptr) {
            throw std::runtime_error(
                "introspection type support has no MessageMembers");
        }

        members_ = static_cast<const MessageMembers*>(
            introspection_handle->data);
        serialization_ =
            std::make_unique<rclcpp::SerializationBase>(
                rmw_type_support_);

        subscription_ = node_.create_generic_subscription(
            topic_,
            type_name_,
            rclcpp::QoS(10),
            [this](
                std::shared_ptr<rclcpp::SerializedMessage> serialized) {
                evaluate(*serialized);
            });
    }

private:
    [[nodiscard]] const MessageMember* findField() const
    {
        for (uint32_t index = 0; index < members_->member_count_; ++index) {
            const auto& member = members_->members_[index];
            if (field_ == member.name_) {
                return &member;
            }
        }
        return nullptr;
    }

    void evaluate(const rclcpp::SerializedMessage& serialized)
    {
        try {
            // Allocate and construct the generated C++ message object using
            // only runtime introspection metadata.
            InitializedMessage message(members_);

            // Deserialize CDR through the active RMW implementation into
            // that initialized message storage.
            serialization_->deserialize_message(
                &serialized,
                message.data());

            const MessageMember* member = findField();
            if (member == nullptr) {
                throw std::runtime_error("configured field was not found");
            }
            if (member->is_array_ ||
                member->type_id_ !=
                    rosidl_typesupport_introspection_cpp::ROS_TYPE_FLOAT) {
                throw std::runtime_error(
                    "configured field is not a scalar float32");
            }

            // offset_ locates the field inside the generated message object.
            // memcpy avoids alignment and aliasing assumptions in generic code.
            const auto* address =
                static_cast<const uint8_t*>(message.data()) +
                member->offset_;
            float value = 0.0F;
            std::memcpy(&value, address, sizeof(value));

            if (value < threshold_) {
                RCLCPP_WARN(
                    node_.get_logger(),
                    "%s.%s is %.3f, below %.3f",
                    topic_.c_str(),
                    field_.c_str(),
                    static_cast<double>(value),
                    static_cast<double>(threshold_));
            }
        } catch (const std::exception& error) {
            RCLCPP_ERROR(
                node_.get_logger(),
                "dynamic rule evaluation failed: %s",
                error.what());
        }
    }

    rclcpp::Node& node_;
    std::string topic_;
    std::string field_;
    std::string type_name_;
    float threshold_;

    // Libraries must remain loaded while their handles and callbacks are used.
    std::shared_ptr<rcpputils::SharedLibrary> rmw_library_;
    std::shared_ptr<rcpputils::SharedLibrary> introspection_library_;
    const rosidl_message_type_support_t* rmw_type_support_{nullptr};
    const MessageMembers* members_{nullptr};
    std::unique_ptr<rclcpp::SerializationBase> serialization_;
    rclcpp::GenericSubscription::SharedPtr subscription_;
};
```

The important internal sequence is visible directly in the code:

```text
ROS graph discovery
  -> "sensor_msgs/msg/BatteryState"

get_typesupport_library(..., "rosidl_typesupport_cpp")
  -> RMW serialization implementation

get_typesupport_library(
    ..., "rosidl_typesupport_introspection_cpp")
  -> MessageMembers schema metadata

MessageMembers::size_of_
  -> allocate enough storage for the generated C++ message object

MessageMembers::init_function
  -> construct strings, vectors, nested messages, and other fields

SerializationBase::deserialize_message
  -> deserialize CDR into the initialized message storage

MessageMember::name_ + type_id_ + offset_
  -> find "percentage", verify float32, and locate its value

MessageMembers::fini_function
  -> destroy all dynamically managed fields

operator delete
  -> release the raw message storage
```

The introspection library still contains generated and compiled support for
`BatteryState`. The monitoring framework does not include the `BatteryState`
C++ header or instantiate a `BatteryState` subscription; it selects and loads
that support through the discovered runtime type name.

Nested paths such as `twist.twist.linear.x` use the same metadata recursively.
When a `MessageMember` has `ROS_TYPE_MESSAGE`, its `members_` handle points to
the nested `MessageMembers`. A resolver advances the storage pointer by
`offset_`, obtains the nested schema from `members_->data`, and repeats for the
next path component. Arrays and sequences use `size_function` and
`get_const_function` rather than direct scalar access.

If the runtime type name, RMW type support, or introspection type support is
unavailable, the framework cannot interpret the fields and must leave the
payload opaque. Type erasure removes the compile-time dependency; it does not
remove the need for runtime type identity, generated type support, and schema.

## Why a generic endpoint still requires a real ROS type

Generic means that the application-facing C++ class is not templated. The
underlying ROS 2 and DDS endpoint remains strongly typed.

For this call:

```cpp
node->create_generic_publisher(
    "/cmd_vel", "geometry_msgs/msg/Twist", qos);
```

ROS approximately performs:

```cpp
auto library = rclcpp::get_typesupport_library(
    "geometry_msgs/msg/Twist", "rosidl_typesupport_cpp");
auto handle = rclcpp::get_typesupport_handle(
    "geometry_msgs/msg/Twist", "rosidl_typesupport_cpp", *library);
```

The resulting handle is used to:

- Create and register the RMW/DDS endpoint.
- Advertise the type through the ROS graph.
- Match publishers and subscribers with the same type identity.
- Provide middleware-specific type metadata.
- Support typed deserialization on the receiving side.

The type name is therefore not redundant. It controls endpoint identity, but
the serialized publishing path does not invoke its serializer for every
message because the caller has already supplied serialized bytes.

The application must keep these two facts consistent:

```text
declared endpoint type = actual type represented by the serialized bytes
```

## Generic and typed endpoint interoperability

Generic and typed endpoints communicate normally when their topic type and
QoS are compatible:

| Publisher | Subscriber | Result |
| --- | --- | --- |
| Typed | Typed | Typed object at both application boundaries |
| Generic | Typed | Sender supplies serialized bytes; receiver gets `T` |
| Typed | Generic | Sender publishes `T`; receiver gets serialized bytes |
| Generic | Generic | Both application boundaries use serialized bytes |

The generic/typed distinction is local to the C++ API. Their ROS/DDS wire
representation is identical.

Endpoint creation verifies that the type name resolves to installed type
support. Discovery also requires compatible topic names, type identities, and
QoS. Publishing a `SerializedMessage`, however, does not reliably validate
that every byte is a correct serialization of the declared type.

## Serialized bytes must match the declared ROS type

### ROS 2 transmission remains strongly typed

The generic C++ API does not make the underlying ROS 2 channel untyped. When a
generic publisher is created, `type_name` selects a real ROS message type and
its installed type support. That type becomes part of the endpoint identity
used by ROS graph discovery, RMW, and DDS.

Every sample on that channel is therefore expected to be the serialized wire
representation of the declared type:

```text
GenericPublisher configured as geometry_msgs/msg/Twist
    requires
SerializedMessage containing a serialized Twist
```

This requirement allows the generic publisher to communicate with every
compatible ROS 2 endpoint. A typed `Subscription<Twist>` can receive the
sample, deserialize it as `Twist`, and expose a valid C++ object. Rosbag,
bridges, routers, and other middleware tools can also process the sample using
the advertised type information.

### Generic publishing can bypass payload validation

`GenericPublisher::publish()` accepts an `rclcpp::SerializedMessage`, so the
application can mechanically place arbitrary bytes in that buffer and ask the
middleware to publish them. The publishing path may not inspect those bytes or
prove that they represent the declared ROS type.

That capability does not change the channel contract. If arbitrary bytes are
published under an unrelated `type_name`, the metadata says one type while the
payload contains another representation:

```text
declared channel type: std_msgs/msg/ByteMultiArray
actual payload bytes: raw Protobuf
```

A generic subscriber that only forwards opaque buffers might appear to work,
because it never decodes the sample. A receiver that follows the ROS type
contract will instead attempt to deserialize those bytes as
`ByteMultiArray`. Deserialization may fail, produce invalid data, or otherwise
behave incorrectly. The same mismatch can break typed subscribers, rosbag,
bridges, content filters, and interoperability with another RMW
implementation.

The distinction is therefore:

```text
Mechanically possible:
    put arbitrary bytes in SerializedMessage and publish them

Valid ROS 2 contract:
    SerializedMessage contains the serialized form of type_name
```

A byte-oriented adapter built on generic pub/sub must expose the second
contract. Its input is not arbitrary application payload; it is a complete
serialized ROS sample whose type matches the endpoint's runtime `type_name`.

## Recommended ROS 2 implementation for opaque payloads

Use a real ROS envelope whose data field carries the opaque payload. A common
choice is `std_msgs/msg/ByteMultiArray`:

```text
Protobuf/custom bytes
  -> ByteMultiArray.data
  -> serialize complete ByteMultiArray as ROS CDR
  -> GenericPublisher configured as ByteMultiArray
```

The receiver performs the inverse:

```text
SerializedMessage
  -> deserialize ByteMultiArray
  -> expose ByteMultiArray.data as the application payload
```

For richer routing and schema information, define a dedicated envelope:

```text
# opaque_msgs/msg/OpaquePayload.msg
string encoding
string schema
uint8[] data
```

The recommended adapter behavior for an arbitrary-byte channel is:

```text
send(payload, size)
  -> construct OpaquePayload or ByteMultiArray
  -> serialize the outer ROS message
  -> GenericPublisher::publish(serialized)

receive(serialized)
  -> deserialize the outer ROS message
  -> callback(payload.data(), payload.size())
```

This preserves an arbitrary-byte application abstraction while remaining
valid for typed ROS subscribers, rosbag record/replay, bridges, and different
RMW implementations.

### Generic publisher example

```cpp
auto publisher = node->create_generic_publisher(
    "/opaque_payload",
    "std_msgs/msg/ByteMultiArray",
    rclcpp::QoS(10));

std_msgs::msg::ByteMultiArray envelope;
envelope.data = protobuf_payload;

rclcpp::Serialization<std_msgs::msg::ByteMultiArray> serializer;
rclcpp::SerializedMessage serialized;
serializer.serialize_message(&envelope, &serialized);
publisher->publish(serialized);
```

### Generic receiver example

```cpp
auto subscription = node->create_generic_subscription(
    "/opaque_payload",
    "std_msgs/msg/ByteMultiArray",
    rclcpp::QoS(10),
    [](std::shared_ptr<rclcpp::SerializedMessage> serialized) {
        std_msgs::msg::ByteMultiArray envelope;
        rclcpp::Serialization<std_msgs::msg::ByteMultiArray> serializer;
        serializer.deserialize_message(serialized.get(), &envelope);
        parseProtobuf(envelope.data);
    });
```

### Typed receiver example

```cpp
auto subscription =
    node->create_subscription<std_msgs::msg::ByteMultiArray>(
        "/opaque_payload",
        rclcpp::QoS(10),
        [](std_msgs::msg::ByteMultiArray::ConstSharedPtr message) {
            parseProtobuf(message->data);
        });
```
