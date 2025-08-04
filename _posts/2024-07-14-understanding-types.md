---
layout: post
title:  "Type systems: Part I"
date:   2024-07-14 10:20:46 +0800
tags: [design_philosophy]
---

Everyday, We deal with all kinds of *data format*: C++ types, Python types, JSON, XML, Protocol Buffers, IDL, ROS msg, etc. JSON and XML are *data format*, others are *type system*. They are two different concepts:

- *data format*: format of the actual *data*. This *data* can come from instances of any *type system*. For example, `struct Msg {string name;}` is a C++ type and it's instances, *data*, can be represented using json as `{"name": "weiqiang.shan"}`
- *type system*: format of *one group* of *data*. Those data share same attributes and is generalized as a *type*. This is about *how data should be organized* and is *abstract idea* about types. It still has nothing to do with *dynamic* or *static* typing.
- *dynamic* and *static* typing system: On top of a *type system*, we can implement a *static* program that can only represent a specific *type*. For example we can define a type: `message Msg{string name = 1;}` in protobuf and write programs to use this type of data. This program can only operate on this specific `Msg` type and no other protobuf messages. So protobuf is essentially a *static typing system*. With *type eraure*, we can implement a *dynamic* typing system, which can represent any kinds of type in one type system. For example, `nlohmann::json` implementation can represent any json data. Note that even though json is not a type system, but a *type system* is required to represent json data, `nlohmann::json` actually defines a *type system* as well as a dynamic typing system based on this *type system*. Python also has it's own *type system* and a dynamic typing system on top of it, also using *type erasure* essentially.

* toc
{:toc}

## Schema

Language/platform neutral way for defining data types.  It consists of pre-defined basic types and rules to build complex customized data types. It is mainly used for data exchange and storage across different languages and platforms. It is compiled into different language code representations, or dynamically loaded by dynamic interpreters.  The most familiar schema languages in the world might be XML Schema(XSD) and JSON Schema. The .xml and .json files we encounter every day are NOT schemas, they are *data* of a XML Schema and JSON Schema respectively. We normally do not deal with the XML Schema or JSON Schema when we write a .xml or .json file, instead we directly write *data* of those schemas. This is because *data* or *serialized data* of  XML Schema and JSON Schema self-contains the XML Schema or JSON Schema. All kinds of XML or JSON parsers can get all the schema information from the *data* to dynamically build types to interpret the *data*. Compared with Protocol Buffers, a .json file is NOT the counterpart of .proto file, instead it is the counter-part of on-wire data of Protocol Buffers. It’s rather counter intuitive. The reason behind this is that both XML and JSON only support and serialize it’ data into human readable text format and it’s data contains all the info of it’s schema, while Protocol Buffers serialize it’s data into binary format. Of course it’s ok if Protocol Buffers choose to use plain text like JSON to encode it’s on-wire format, but it’s in the expense of speed and efficiency. In exchange for speed and efficiency, it’s is required in the receiver side to know the schema to decode the on-wire data, unless the schema itself is encoded and send together with data. We will talk about this latter.

## Language binding

For dynamic interpreter, every programming language should have a program to dynamically load and built type and instance from pre-defined schemas.
For static interpretation, there should be a *compiler* to compile *schema* into specific language representations.


### Type Interpreter

JSON/XML/Proto/ROS/C/C++ are all *data format*. It consists of pre-defined basic types and rules to build complex customized data types. They can be interpreted statically or dynamically. *data format* by themselves have nothing to do with *dynamic* or *static*, it's the *interpreter* that parse them have the attributes of those two distinct feature. The same data format can be interpreted both dynamically and statically at the same time, depending on the interpreter/program used to parse them. Normally, C/C++ types are processed statically, which is why it's called static-typed language. Python types are processed by python interpreter dynamically. Proto/ROS/IDL are first compiled into C/C++ types and processed statically. JSON/XML both have dynamic and static interpreters. For example, the `nlohmann::json` library can dynamically parse *any* json files, while in many critical industries there is statical json parsers that is hard coded to only parse specific json data structure(like in AUTOSAR manifest files), they differ in that dynamic json parser will dynamically store any inputs in memory, which static json parser is programmed to parse pre-determined json data structures(json structure is pre-known before runtime, like Proto/IDL/ROS). **In the rest of this artical, when we say *dynamic* or *static*, we mean the *program/interpreter* that parse types, NOT the type themselves**.


#### Static Interpreter

The main characteristic of those type interpreter is that after compiling, all type information is lost. Type information of a variable, like type name, type, member name, member type, are translated by compiler into machine code directly. Those types only lives *before* compilation. Representitives of this kind of types is C. 

#### Introspection

*Introspection* means that type information can be retrieved at *runtime*. This means that type information of a variable lives at runtime. We can get the type information through specific API. To achieve this, static variables and functions are required for a specific type. Those *introspection* variables and codes are compiled into text and data segment of ELF file. At runtime, caller need to know the type name(string literal, for example) to get the relevent introspection information. An example is ROS2 type system. In ROS2, the ROS2 compiler will compile the *.msg* file into language-specific type representations. At the same time, introspection codes and static variables that store type information for every type are generated. Every type is identified by it's unique *path*(string literal) and at runtime, by using this *path*, the introspection information can be retrieved(this normally involves global function naming convention together with the type path, and the use of *dlopen* and *dlsym* to find symbols in shared libraries, which is how ROS2 support introspection). C++ is mostly static types, however it can use RTTI to support *introspection*.

#### Reflection

*The ability to inspect the code in the system and see object types is not reflection, but rather Type Introspection. Reflection is then the ability to make modifications at runtime by making use of introspection. The distinction is necessary here as some languages support introspection, but do not support reflection. One such example is C++.* [source](https://stackoverflow.com/questions/37628/what-is-reflection-and-why-is-it-useful). According to this definition, reflection supports modification of the *values* of variable instance through *introspection*. Note that reflection can not change *type*, only *value* for variable instance. Besides, reflection can also create new instance. One classic [implementation of reflection is Google Protobuffers](https://shan-weiqiang.github.io/2025/06/14/protobuf-reflection.html).

#### Dynamic interpreter

Introspection can be implemented *statically* or *dynamically*. Like we mentioned above, ROS2 supports *introspection*  statically, since all the codes and static variables that contains type information are *statically* generated and compiled into machine code at compile time.

What if we can read those type information at *runtime*, without knowing the type information at compile time? This is *dynamic interpretation*. The dynamic interpreter will dynamically build types based on any kinds of *type representation*, as long as it contains valid type information. 

*The key difference with reflection is that in dynamic interpretation types can be created at runtime according to schemas, not only it's value.*  The schemas can be read from file or programmatically added into the dynamic interpreter. 

Another main feature of dynamic interpretation is it can create type instances dynamically according to type information. This type instances does NOT necessarily has the same memory layout with it's static interpretation couter part. For example, in Xtypes, the statically generated IDL C++ type does not have the same memory layout with the instance created by dynamically loading the xml type schema(then created by the dynamic interpreter). Also the protoc-generated C++ types, does not have the same memory layout with the *DynamicMessage*, which is created at runtime, without statically generated type information. However, both of the so-called dynamic instance and the static instance adhere to a type *schema*, and they contain the same information and can do same operations on them, such as serialization and deserialization. 

*Dynamic interpretation* is NOT *dynamic types*, because it must adhere to a pre-defined *schema*, just like static generated types. **Once the schema is built, it's fixed and is used as a *blueprint* to build type instances. However, true dynamic types, like nlohmann::json and Python does not have pre-defined schemas**.


## Self-hosting

Type system or schema language is self-hosting if it can use  it’s type or schema to describe  other types or schemas. It’s a rather tricky concept. The type system or schema language should not be too simple as to not have enough expressiveness to describe all it’s features. At the same time, it should not be too complex as to make it impossible for it to describe itself. It’s like a competition between expressiveness and complexcity of the type system and the schema language itself. For example, C++ type system is so complex that we normally do not use C++ types to represent another C++ type, even given that C++ type’s great expressiveness. Protocol Buffers is not that complex and have enough expressiveness so that we can use one single *descriptor.proto* schema to describe all possible other Protocol Buffers schemas, making Protocol Buffers self-hosting.


## Schema and Data

After we understand what is self-hosting, we better take the chance to have a deep look at what is *schema*  and what is *data*. Simply put: *data* is actualization of *schema,* and for self-hosting schema languages, we can use *data*  of one special schema to represent another schema, we call this special schema, *meta-schema*, or, *schema of schemas*. For schema languages like XML Schema, or JSON Schema, there is no need for the meta-schema, since every data can contains it’s schema in itself. We do not need another special schema to carry the schema information of it’s data. But for Protocol Buffers and OMG XTypes, the schema info is not carried in every encoded data. One way to carry schema info is to encode all schema info into data, which like said before is inefficient. Another way is to use the text format .proto or .idl file directly, which is feasible but also inefficient. The final way that adopted both by Protocol Buffers and OMG XTypes is to use it’s self-hosting feature to define a meta-schema that can carry information of another schema. This way, the schema information can be encoded *the same* with data and can be transmitted on-wire. This meta-schema is often a built-in schema in those schema languages, for example *type_object.idl*, or *descriptor.proto*, and their compiled C++ class are *TypeObject* and *DescriptorProto,* in XTypes and Protocol Buffers respectively. Instance of those class carries the same information as a proto or idl file. In dynamic interpretation we will latter talk about, those built-in schemas will be used as input to build types, since they are equal to schema files. In Protocol Buffers, the *DescriptorProto* calss will be based to construct *Descriptor* class, which represents a type. In XTypes, *TypeObject* will be based to construct a *DynamicType*. Based on those types, *dynamic data* can be realized and be used to decode schema data dynamically.


## Real dynamic types systems

The most outstanding characteristic of true dynamic typing is that **it does not need a pre-defined *schema*. There exists one single class to represent all possible types and values.** `json` in `nlohmann::json`, `PyObject` in Python, they both have this pattern. **Only by this true dynamic can be achieved, since this is the only way to use one set of static codes to represent all possible types**. How can this be done? Type erasure. [nlohmann json](https://github.com/nlohmann/json) use union to store all possbile types; CPython use OOP, which is essentially the same as C++'s abstract class. A union and an abstract class can store any types, great!

