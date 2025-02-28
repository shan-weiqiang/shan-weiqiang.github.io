# Compare

- *Atomic unit of Execution(AUE)*: The smallest unit that can be scheduled on CPU/GPU; A C++ callable object; Can not start new thread inside it. This concept is closely related to OS and hardware concept.
- *Atomic Algorithmic unit of Execution(AAE)*: The smallest unit that group an functionality. For example fusion, planning. It groups one or more AEs and act as programming interface to applcation developers. The communication between AEs and AAEs are different:
  - AUE can only communicate with other AEs that are inside the same AAE. They exchange data through shared variables.
  - AAE accept inputs and send output to other AAEs through IPC channels. 
- *Port*: Data transfer channels between AAEs.
- *Graph*: DAG graph composed by AAEs(in AOS, AUE can also construct dag).
- *Graphlet*: Subgraph inside a bigger graph.
- *Component*: One AAE or one graphlet.

|                         | DriveWorks                  | AOS                      | Cyberrt              |
| ----------------------- | --------------------------- | ------------------------ | -------------------- |
| AUE[5]                  | Pass                        | Runnable                 | Component(Coroutine) |
| AAE[5]                  | Node[4]                     | Activity[3]              | Node[1]              |
| Port[5]                 | Channel                     | Topic                    | Topic                |
| Graph                   | Node DAG                    | Runnable/Activity DAG[2] | Component DAG        |
| Graphlet                | Subgraph                    | NULL                     | NULL                 |
| Model Format            | JSON(DAG)/YAML(STM)         | YAML                     | NULL                 |
| Compiler                | `nodestub`/`stmcompiler`[6] | `yaaac`                  | NULL                 |
| Deterministic Recompute | Not Found                   | YES                      | NO                   |

Note:

1. Cyberrt Node can be used by multiple Component. It is not the same as Node in DriveWorks or Activity in AOS:
   1. Node in DriveWorks or Activity in AOS *contains* Pass or Runnable respectively, Pass or Runnable can communicate with each other in the same scope of Node or Activity, for example shared class member variables.
   2. Node in Cyberrt *serve* one or multiple Components by providing communication. Component communication in Cyberrt is comparable to Node/Activity communication in DriveWorks and AOS.
2. AOS has DAG both for Runanble and Activity
3. AOS Activity is consisted of a DAG of Runnables
4. DriveWorks Node is consisted of a sequential(default) execution of Pass: [Compute Graph Framework SDK Reference](https://developer.nvidia.com/docs/drive/drive-os/6.0.9/public/driveworks-nvcgf/index.html)
5. Those concept will be reflected in C++ code
6. DriveWorks' CGF and STM is two different SKD: [System Task Manager SDK Reference](https://developer.nvidia.com/docs/drive/drive-os/6.0.7/public/driveworks-stm/index.html)

The different concept leads to different strategy when dealing with those middleware, especially scheduling and deterministic replay. In all of those three middlewares, scheduling both happens at the AUE level. But for deterministic recompute control, DriveWorks and AOS use Node and Activity as control unit, Cyberrt use Component as control unit. 

# DriveWorks STM

[Compute Graph And Constraints](https://developer.nvidia.com/docs/drive/drive-os/6.0.7/public/driveworks-stm/stm_compiler_computegraphandconstraints.html)

The CGF and STM in DriveWorks has orthogonal relationship.

- `runnable` in STM is directly mapped from `Pass` in CGF, which is a AUE
- `client` in STM is a OS process, which can contain one or more `Node` in CGF

The compute graph(YAMLs) for STM is compiled from CGF(JSON), taking the Node relationship into consideration.

All runnables are scheduled by STM periodically, through the concept of hyperepoch and epoch. Hyperepoch is a rough periodical time and epoch is nested inside hyperepoch:

```yaml
Hyperepochs: 
- 100ms_hyper: # executed every 100ms
    Period: 100ms
    Resources: [CPU1, CPU2, GPU0] # each hyperepoch can have resources
    Epochs: # hyperepoch contain multiple epochs
    - Camera:
        Period: 10ms # Camera epoch will be executed 8 times, with interval 10ms
        Frames: 8
    - Radar:
        Period: 100ms # Radar epoch will be 1 time
    - Planning:
        Period: 33ms
        Frames: 3
- 50ms_hyper:
    Period: 50ms
```

Each epoch can have multiple runnables and they will be run during this epoch time slot. Runnables are defined in compute graph yaml files for `client`:

```yaml
Version: 2.0.0
Drive: # Graph ID
Clients:
- Client0: # Client ID
    Resources: # Client0s internal resources
    # Resource Definition
    Epochs: # Epochs present in this client
    - Perception.Camera: # Epoch Global ID - <HyperepochID.EpochID>
        Runnables: # Runnables present in Perception.Camera
        - ReadCamera: # Runnable ID (Unique inside a client)
        - RunnableN:
    - Perception.Radar:
        Runnables: # Runnables present in Perception.Radar
        - ProcessRadar:
```

Each runnable(Pass in CGF) in clients(OS processes) is configured in above yaml files and `stmcompiler` compiles them to final statical scheduling manifest. Each client has a thread pool to run all the runnables. STM daemon read the scheduling manifest and controls the execution in each client globally.

[STM](https://developer.nvidia.com/docs/drive/drive-os/6.0.7/public/driveworks-stm/stm_introduction.html)

Features:

- A CPU Runnable is represented as a callback function (C/C++) that is registered with the STM run-time. STM maintains a pool of worker threads that will call the clients registered functions at the appropriate offset in the schedule.
- One important aspect of STM is that it ever schedules one single pass per hardware engine - never multiple concurrently. This means that one CPU/GPU at a specific time point only have one job to process, preventing scheduling influence from underlying OS.
- System Task Manager (STM) is a static, centrally-monitored, OS-agnostic, non-preemptive user-space scheduler that manages the work across hardware engines. Based on the information from the DAG, a schedule configuration, and the worst-case execution time (WCET) for each pass the STM compiler generates a static schedule. 
  - STM need WCET time to generate static configuration, it is a time-buget system!
  - After WCET is determined, STM can deterministically schedule all runnables
  - STM is non-preemptive, so internally it have to control the statically determined execution order. This implies that it can only keep the results deterministic, but not for the actual execution time.
- The execution time line is decided by hyperepoch and epoch, which acts very much like simulation time! All runnables are registered in periodical epochs!
