from tqdm import tqdm
import networkx as nx
import json
import os
import hashlib
import base64

mapping_dict = {
    "Host": 2,
    "Principal": 3,
    "Subject": 4,
    "FileObject": 5,
    "UnnamedPipeObject": 6,
    "NetflowObject": 8,
    "SrcSinkObject": 9,
    "RegistryKeyObject": 12,
    2: "Host",
    3: "Principal",
    4: "Subject",
    5: "FileObject",
    6: "UnnamedPipeObject",
    8: "NetflowObject",
    9: "SrcSinkObject",
    12: "RegistryKeyObject"
}

attack_durations = [
    (1523028000000000000, 1523030940000000000),
    (1523473620000000000, 1523474160000000000),
    (1523555940000000000, 1523558340000000000),
    (1523624580000000000, 1523625540000000000)
]

with open("/home/cpsc538p/Documents/SummDetector/Nodemerge/uuid_exec_maps.json", 'r') as f:
    uuid_exec_maps = json.load(f)
    f.close()

with open("/home/cpsc538p/Documents/SummDetector/Nodemerge/index_file.json", 'r') as f:
    index_uuid_maps = json.load(f)
    f.close()



def hashgen(hashstr):
    hasher = hashlib.md5()
    hasher.update(str(hashstr).encode("utf-8"))
    return hasher.hexdigest()

def get_subject_label(uuid_exec_maps, index_uuid_maps, subject_id):
    try:
        subject_uuid = index_uuid_maps[subject_id]
        exec_name = uuid_exec_maps[subject_uuid]
    except:
        exec_name = "null"
    return str(exec_name)

def get_decoded_path(base64_encoded_path):
    a = base64.b64decode(base64_encoded_path.encode('ascii'))
    return a.decode('ascii')


############################################## Training set #############################################
train_graph_0_path = "/scratch/cadet_graphs_attr/Training_Graphs/graph_0.edgelist"
train_graph_1_path = "/scratch/cadet_graphs_attr/Training_Graphs/graph_1.edgelist"
train_graph_2_path = "/scratch/cadet_graphs_attr/Training_Graphs/graph_2.edgelist"


train_graph_0 = nx.MultiDiGraph(nx.read_edgelist(train_graph_0_path))
train_graph_1 = nx.MultiDiGraph(nx.read_edgelist(train_graph_1_path))
train_graph_2 = nx.MultiDiGraph(nx.read_edgelist(train_graph_2_path))

train_graph = nx.compose_all([train_graph_0, train_graph_1, train_graph_2])
sorted_train_edges = sorted(train_graph.edges(data=True, keys=True), key=lambda x: x[3].get('timestamp'))

i = 0
file_no = 0
batch_size = int(len(sorted_train_edges) / 100)
logical_time = 0

file = open("./train/benign_{}.csv".format(file_no), 'w')
for edge in sorted_train_edges:
    src_id = edge[0]
    dst_id = edge[1]
    src_type = str(mapping_dict[edge[3]['source_type']])
    src_label = src_type + "_" + get_subject_label(uuid_exec_maps, index_uuid_maps, src_id)
    hashed_src_label = hashgen(src_label)

    dst_type = str(mapping_dict[edge[3]['dest_type']])
    if "File" in dst_type:
        file_object_path = edge[3]['attr']
        if file_object_path:
            dst_label = dst_type + "_" + get_decoded_path(file_object_path)
        else:
            dst_label = dst_type + "_" + "null"
    elif "Netflow" in dst_type:
        ip_addr = edge[3]['attr'].replace(":", "_")
        dst_label = dst_type + "_" + ip_addr
    elif "Subject" in dst_type:
        exec_name = get_subject_label(uuid_exec_maps, index_uuid_maps, dst_id)
        dst_label = dst_type + "_" + exec_name
    else:
        dst_label = dst_type + "_" + "null"

    hashed_dst_label = hashgen(dst_label)
    edge_type = edge[3]['event_type'].encode("utf-8")
    hashed_edge_type = hashgen(edge_type)

    file.write("{} {} {}:{}:{}:{}\n".format(src_id, dst_id, hashed_src_label, hashed_dst_label, hashed_edge_type,
                                            logical_time))
    logical_time += 1
    i += 1
    if i == batch_size:
        file.close()
        file_no += 1
        file = open("./train/benign_{}.csv".format(file_no), 'w')
        i = 0
file.close()

############################################## Testing set #############################################
test_graph_0_path = "/scratch/cadet_graphs_attr/Testing_Graphs/graph_0.edgelist"
test_graph_1_path = "/scratch/cadet_graphs_attr/Testing_Graphs/graph_1.edgelist"
test_graph_2_path = "/scratch/cadet_graphs_attr/Testing_Graphs/graph_2.edgelist"
test_graph_3_path = "/scratch/cadet_graphs_attr/Testing_Graphs/graph_3.edgelist"
test_graph_4_path = "/scratch/cadet_graphs_attr/Testing_Graphs/graph_4.edgelist"
test_graph_5_path = "/scratch/cadet_graphs_attr/Testing_Graphs/graph_5.edgelist"
test_graph_6_path = "/scratch/cadet_graphs_attr/Testing_Graphs/graph_6.edgelist"
test_graph_7_path = "/scratch/cadet_graphs_attr/Testing_Graphs/graph_7.edgelist"
test_graph_8_path = "/scratch/cadet_graphs_attr/Testing_Graphs/graph_8.edgelist"


test_graph_0 = nx.MultiDiGraph(nx.read_edgelist(test_graph_0_path))
test_graph_1 = nx.MultiDiGraph(nx.read_edgelist(test_graph_1_path))
test_graph_2 = nx.MultiDiGraph(nx.read_edgelist(test_graph_2_path))
test_graph_3 = nx.MultiDiGraph(nx.read_edgelist(test_graph_3_path))
test_graph_4 = nx.MultiDiGraph(nx.read_edgelist(test_graph_4_path))
test_graph_5 = nx.MultiDiGraph(nx.read_edgelist(test_graph_5_path))
test_graph_6 = nx.MultiDiGraph(nx.read_edgelist(test_graph_6_path))
test_graph_7 = nx.MultiDiGraph(nx.read_edgelist(test_graph_7_path))
test_graph_8 = nx.MultiDiGraph(nx.read_edgelist(test_graph_8_path))

test_graph = nx.compose_all([
    test_graph_0,
    test_graph_1,
    test_graph_2,
    test_graph_3,
    test_graph_4,
    test_graph_5,
    test_graph_6,
    test_graph_7,
    test_graph_8
])
sorted_test_edges = sorted(test_graph.edges(data=True, keys=True), key=lambda x: x[3].get('timestamp'))
base_timestamp = 1522706861813350340

batch_size = int(len(sorted_test_edges) / 100)
file_names = []
logical_time = 0

benign_file_no = 0
attack_file_no = 0
for i in range(0, len(sorted_test_edges), batch_size):
    batched_edges = sorted_test_edges[i:i + batch_size]
    is_attack = False
    for edge in tqdm(batched_edges, desc="Batch {}".format(benign_file_no + attack_file_no)):
        edge_time = edge[3]['timestamp'] + base_timestamp
        for start_time, stop_time in attack_durations:
            if edge_time >= start_time and edge_time <= stop_time:
                is_attack = True
                break
    if is_attack:
        file_names.append("./test/attack_{}.csv".format(attack_file_no))
        attack_file_no += 1
    else:
        file_names.append("./test/bengin_{}.csv".format(benign_file_no))
        benign_file_no += 1

    file = open(file_names[-1], 'w')
    for edge in batched_edges:
        src_id = edge[0]
        dst_id = edge[1]
        src_type = str(mapping_dict[edge[3]['source_type']])
        src_label = src_type + "_" + get_subject_label(uuid_exec_maps, index_uuid_maps, src_id)
        hashed_src_label = hashgen(src_label)

        dst_type = str(mapping_dict[edge[3]['dest_type']])
        if "File" in dst_type:
            file_object_path = edge[3]['attr']
            if file_object_path:
                dst_label = dst_type + "_" + get_decoded_path(file_object_path)
            else:
                dst_label = dst_type + "_" + "null"
        elif "Netflow" in dst_type:
            ip_addr = edge[3]['attr'].replace(":", "_")
            dst_label = dst_type + "_" + ip_addr
        elif "Subject" in dst_type:
            exec_name = get_subject_label(uuid_exec_maps, index_uuid_maps, dst_id)
            dst_label = dst_type + "_" + exec_name
        else:
            dst_label = dst_type + "_" + "null"

        hashed_dst_label = hashgen(dst_label)
        edge_type = edge[3]['event_type'].encode("utf-8")
        hashed_edge_type = hashgen(edge_type)

        file.write("{} {} {}:{}:{}:{}\n".format(src_id, dst_id, hashed_src_label, hashed_dst_label, hashed_edge_type,
                                                logical_time))
        logical_time += 1
    file.close()
