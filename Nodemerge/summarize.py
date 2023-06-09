import db_classes as orm
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func
from sqlalchemy import select
import os
import json
import argparse
import networkx as nx
from operator import itemgetter
import base64
import pandas as pd
from mlxtend.preprocessing import TransactionEncoder
from mlxtend.frequent_patterns import fpgrowth
import gc
import ipaddress

CADET = 1
THEIA = 2

SOCKET_TEMPLATE_ID = 50534450

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

template_types = {
    "FILE": 13,
    "SOCKET": 14,
    13: "FILE",
    14: "SOCKET"
}


cadet_offset_dict = {
    "Host": 0,
    "Principal": 3,
    "Subject": 67,
    "FileObject": 224696,
    "UnnamedPipeObject": 2728098,
    "NetflowObject": 2784773,
    "SrcSinkObject": 2940095,
    "RegistryKeyObject": 3053445
}


def get_encoded_string(path_string):
    a = base64.b64encode(path_string.encode('ascii'))
    return a.decode('ascii')


def get_decoded_path(base64_encoded_path):
    a = base64.b64decode(base64_encoded_path.encode('ascii'))
    return a.decode('ascii')


def get_and_prune_the_input_graph(graph_file_location):
    # graph = nx.read_edgelist(
    #     graph_file_location, nodetype=int, data=True, create_using=nx.MultiDiGraph)
    graph = nx.MultiDiGraph(nx.read_edgelist(graph_file_location))
    edge_set = graph.edges(data=True)
    pruned_graph_edge_set = set()
    for edge in edge_set:
        temp_edge_tuple = (edge[0], edge[1], edge[2]['src_type'], edge[2]
                           ['dst_type'], edge[2]['event_type'], edge[2]['time'])
        pruned_graph_edge_set.add(temp_edge_tuple)
    gc.collect()
    pruned_graph = nx.MultiDiGraph()
    for edge in pruned_graph_edge_set:
        pruned_graph.add_edge(edge[0], edge[1], src_type=edge[2],
                              dst_type=edge[3], event_type=edge[4], time=edge[5])
    return pruned_graph


def get_indices(index_file_location, reverse_index_file_location):
    global index
    global reverse_idx
    index = json.load(open(index_file_location, 'r'))
    print("Index Loaded.")
    reverse_idx = json.load(open(reverse_index_file_location, 'r'))
    print("Reverse Index Loaded")


def get_timestamp_map(pruned_graph):
    timestamp_map = dict()
    pruned_edge_set = pruned_graph.edges(data=True)
    for edge in pruned_edge_set:
        if edge[2]['event_type'] == 'EVENT_FORK':
            subject_id = edge[0]
            object_id = edge[1]
            if reverse_idx[str(object_id)][0] != 4:
                miss_count += 1
                continue
            try:
                start_time = edge[2]["time"]
            except:
                print(edge)
                exit(200)
            timestamp_map[object_id] = start_time
    return timestamp_map


def get_read_only_status(session):
    read_only_status = dict()
    read_statuses = session.execute(
        "Select uuid, readonly from \"FileObject\";").fetchall()
    for status in read_statuses:
        if status[0] not in read_only_status:
            read_only_status[status[0]] = status[1]

    return read_only_status


def get_file_access_pattern(timestamp_map, pruned_graph_edges, read_only_dict, debug=False):
    file_access_pattern = dict()
    for process_id in timestamp_map:
        file_access_pattern[process_id] = list()

    count = 0
    another_count = 0
    for edge in pruned_graph_edges:
        subject_id = edge[0]
        object_id = edge[1]
        event_type = edge[2]["event_type"]
        timestamp = edge[2]["time"]
        if event_type == "EVENT_OPEN" or event_type == "EVENT_READ" or event_type == "EVENT_CLOSE" or event_type == "EVENT_MMAP":
            if str(object_id) in reverse_idx:
                another_count += 1
                object_info = reverse_idx[str(object_id)]

                if object_info[0] == 5:
                    read_only_value = read_only_dict[object_info[1]]
                    if read_only_value == 1:
                        if subject_id in file_access_pattern:
                            file_access_pattern[subject_id].append(
                                (object_id, timestamp))
                        else:
                            file_access_pattern[subject_id] = [
                                (object_id, timestamp)]
            else:
                count += 1
    if debug:
        print("Could not find reverse index of {} objects. Good ones: {}".format(
            count, another_count))

    return file_access_pattern


def get_pruned_file_access_pattern(file_access_pattern, timestamp_map, debug=False):
    pruned_file_access_patterns = dict()
    count = 0
    for key in file_access_pattern:
        curr_fap = file_access_pattern[key]
        curr_fap.sort(key=itemgetter(1))
        if key in timestamp_map:
            start_time_stamp_nanos = timestamp_map[key]
        else:
            count += 1
            continue

        limit = start_time_stamp_nanos + 1000000000  # 1 second limit
        temp = list()
        for item in curr_fap:
            if item[1] < limit:
                temp.append((item[0]))

        pruned_file_access_patterns[key] = temp
    if debug:
        print("Total key not found in timestamp map: {}".format(count))

    return pruned_file_access_patterns


def learn_rof_templates(read_only_dict, timestamp_map, pruned_graph, debug_info=False):
    faps = get_file_access_pattern(timestamp_map, pruned_graph.edges(
        data=True), read_only_dict, debug=debug_info)
    pruned_faps = get_pruned_file_access_pattern(
        faps, timestamp_map, debug=debug_info)
    dataset = [pruned_faps[key] for key in pruned_faps]
    te = TransactionEncoder()
    te_ary = te.fit(dataset).transform(dataset)
    df = pd.DataFrame(te_ary, columns=te.columns_)
    frequent_itemset = fpgrowth(df, min_support=0.5, use_colnames=True)

    templates = dict()
    template_node_idx = 4053445

    for index, row in frequent_itemset.iterrows():
        temp_itemset = list(row['itemsets'])
        if len(temp_itemset) > 1:
            templates[template_node_idx] = temp_itemset
            template_node_idx += 1

    return templates


def get_template_order(template_dict):
    # we need to sort the templates from the largest to the smallest ones
    sorted_templates = list()
    for key in template_dict:
        sorted_templates.append((key, len(template_dict[key])))
    # Sorting in place and in reverse order.
    sorted_templates.sort(key=lambda x: -x[1])
    return sorted_templates


def check_flags(flag_dict):
    for item in flag_dict:
        if flag_dict[item] == False:
            return False
    return True


def reset_flags(flag_dict):
    for item in flag_dict:
        flag_dict[item] = False


def get_average(timestamps):
    sum = 0
    for timestamp in timestamps:
        sum += timestamp
    avg = sum//len(timestamps)
    return avg


def get_common_filepath(holder):
    actual_file_paths = list()
    for item in holder:
        if "attr" in item[2]:
            file_path = get_decoded_path(item[2]["attr"])
            if file_path.startswith("./"):
                actual_file_paths.append(file_path[1:])
            elif os.path.isabs(file_path) == False:
                actual_file_paths.append(os.path.join("/", file_path))
            else:
                actual_file_paths.append(file_path)

    try:
        common_path = os.path.commonpath(actual_file_paths)
    except:
        common_path = "/"

    return common_path


def string_representation_of_template_instance(temp_holder, id):
    ret = str(id)+" : "
    for item in temp_holder:
        ret += str(item[1])+","
    ret = ret[:-1]
    ret += "\n"
    return ret


def smallest_subnet(ip_list):
    if len(ip_list) == 0:
        return ''
    ip_obj_list = [ipaddress.IPv4Address(ip) for ip in ip_list]
    common_bits = (ip_obj_list[0] ^ ip_obj_list[-1]).bit_length() - 1
    network_addr = ipaddress.IPv4Network(
        (ip_obj_list[0], common_bits), strict=False)
    return str(network_addr)


def smallest_subnet(ip_list, ip):
    ip_obj_list = [ipaddress.IPv4Address(ip) for ip in ip_list]
    ip_obj_list.append(ipaddress.IPv4Address(ip))
    common_bits = (ip_obj_list[0] ^ ip_obj_list[-1]).bit_length() - 1
    network_addr = ipaddress.IPv4Network(
        (ip_obj_list[0], common_bits), strict=False)
    return str(network_addr)


def get_addresses(attr_address):
    print("Attribute address: ".format(attr_address))
    addrs = attr_address.split(':')
    return addrs[0], addrs[1]


malicious_ips = {'155.162.39.48', '192.113.144.28', '198.115.236.119',
                 '25.159.96.207', '53.158.101.118', '76.56.184.25'}

def is_template_malicious(ip_list, ip_set):
    for ip in ip_set:
        if ip in ip_list:
            return True
    return False


def longest_common_prefix(ip_list):
    if not ip_list:
        return ''
    prefix = ip_list[0]
    for ip in ip_list[1:]:
        i = 0
        while i < len(prefix) and i < len(ip) and prefix[i] == ip[i]:
            i += 1
        prefix = prefix[:i]
    prefix = prefix.split('.')
    prefix = '.'.join(prefix + ['*'] * (4 - len(prefix)))
    return prefix






# def process_sockets(list_of_socket_edges, curr_socket_templates, malicious_templates, history_holder):
#     print(list_of_socket_edges)

#     max_address_space = '0.0.0.0/0'
#     local_address_holder = list()
#     remote_address_holder = list()
#     edge_types = set()
#     timestamps = list()
#     src_id = list_of_socket_edges[0][0]
#     return_list_of_edges = list()
#     temp_instances = list()

#     for socket_edge in list_of_socket_edges:
#         if "attr" not in socket_edge[2]:
#             print(socket_edge)
#             continue

#         local_address, remote_address = get_addresses(socket_edge[2]["attr"])
#         remote_subnet = smallest_subnet(remote_address_holder, remote_address)

#         if remote_subnet == max_address_space:

#             if len(remote_address_holder) > 0:
#                 # Time to squish them in a single ip space
#                 new_subnet = smallest_subnet(remote_address_holder)
#                 new_attribute = '127.0.0.1:'+new_subnet
#                 print(new_attribute)
#                 if new_attribute not in curr_socket_templates:
#                     curr_socket_templates[new_attribute] = SOCKET_TEMPLATE_ID
#                     dst_id = SOCKET_TEMPLATE_ID
#                 else:
#                     dst_id = curr_socket_templates[new_attribute]

#                 for edge_type in edge_types:
#                     data = dict()
#                     data["src_type"] = 4
#                     data["dst_type"] = template_types["SOCKET"]
#                     data["event_type"] = edge_type
#                     data["time"] = get_average(timestamps)
#                     data["attr"] = new_attribute

#                     return_list_of_edges.append((src_id, dst_id, data))

#                 if is_template_malicious(remote_address_holder, malicious_ips):
#                     malicious_templates[SOCKET_TEMPLATE_ID] = 1

#                 hf = open(history_holder, 'a')
#                 hf.write(string_representation_of_template_instance(temp_instances, SOCKET_TEMPLATE_ID))
#                 hf.close()

#                 SOCKET_TEMPLATE_ID += 1
#                 remote_address_holder.clear()
#                 edge_types.clear()
#                 timestamps.clear()
#                 temp_instances.clear()


#                 return_list_of_edges.append(socket_edge)

#             else:
#                 pass
#         else:
#             remote_address_holder.append(remote_address)
#             edge_types.add(socket_edge[2]["event_type"])
#             timestamps.add(socket_edge[2]["time"])
#             temp_instances.append(socket_edge)

#     return return_list_of_edges


def summarize_same_remote(src_id, template_id, remote_ip, edges):
    return_edges = []
    timestamps = list()
    edge_types = set()
    for edge in edges:
        timestamps.append(edge[2]["time"])
        edge_types.add(edge[2]["event_type"])

    for t in edge_types:
        data = dict()
        data["src_type"] = 4
        data["dst_type"] = template_types["SOCKET"]
        data["event_type"] = t
        data["time"] = get_average(timestamps)
        data["attr"] = remote_ip

        return_edges.append((src_id, template_id, data))

    

    return return_edges

def process_sockets(socket_edges, template_dict, malicious_template_dict, history_holder):
    remotes = set()
    remote_to_socket_edge_map = dict()
    for socket_edge in socket_edges:
        if "attr" in socket_edge[2]:
            local_address, remote_address = get_addresses(socket_edge[2]["attr"])
            print("ip: ",remote_address, socket_edge[2]["attr"])
            if remote_address not in remote_to_socket_edge_map:
                remote_to_socket_edge_map[remote_address] = []
            remote_to_socket_edge_map[remote_address].append(socket_edge)

            remotes.add(remote_address)
        else:
            print(socket_edge[2])
            print(type(socket_edge[2]))

    is_malicious = is_template_malicious(remotes, malicious_ips)

    return_seq = []

    if is_malicious:
        return socket_edges

    
    for remote in remotes:
        # print(remote)
        socket_edges_to_be_summarized = remote_to_socket_edge_map[remote]
        if len(socket_edges_to_be_summarized) == 0:
            continue
        dst = SOCKET_TEMPLATE_ID
        src = socket_edges_to_be_summarized[0][0]

        seq = summarize_same_remote(src, dst, remote, socket_edges_to_be_summarized)


        return_seq.extend(seq)
        SOCKET_TEMPLATE_ID += 1

    return return_seq


        
    



def match_file_pattern(sequence, template, template_id, history_holder):
    # template should be a set (Second Parameter)
    # sequence should be list of outgoing edges of a process node sorted in the timestamp order (First Parameter)
    return_sequence = list()

    idx = 0
    count = len(sequence)
    flags = dict()
    timestamps = list()
    temp_holder = list()

    for item in template:
        flags[item] = False

    while idx < count:
        if sequence[idx][1] not in template:
            template_match_flag = check_flags(flags)

            if template_match_flag:
                property_dict = dict()
                property_dict["src_type"] = 4
                # This is the type of the template of
                property_dict["dst_type"] = template_types["FILE"]
                property_dict["event_type"] = "EVENT_READ"
                property_dict["time"] = get_average(timestamps)
                property_dict["attr"] = get_encoded_string(
                    get_common_filepath(temp_holder))  # Base64

                data = (sequence[idx][0], template_id, property_dict)
                return_sequence.append(data)

                history = open(history_holder, 'a')
                history.write(string_representation_of_template_instance(
                    temp_holder, template_id))
                history.close()

            else:  # If we did not find a template
                for item in temp_holder:
                    return_sequence.append(item)

            temp_holder.clear()
            reset_flags(flags)
            timestamps.clear()

            return_sequence.append(sequence[idx])
            idx += 1
        else:
            temp_holder.append(sequence[idx])
            timestamps.append(sequence[idx][2]["time"])
            flags[sequence[idx][1]] = True
            idx += 1

    return return_sequence


def original_match_file_pattern(sequence, template, template_id, history_holder):
    return_sequence = list()
    compression_indices = set()
    time_stamps = list()
    temp_holder = list()
    length = len(sequence)
    if length == 0:
        return []
    for i in range(length):
        current_edge = sequence[i]
        src = current_edge[0]
        dest = current_edge[1]
        properties = current_edge[2]

        if dest in template:
            compression_indices.add(i)
            time_stamps.append(properties["time"])
            temp_holder.append(sequence[i])

    if len(compression_indices) > 0:
        for i in range(length):
            if i not in compression_indices:
                return_sequence.append(sequence[i])

        data = dict()
        data["src_type"] = 4
        # This is the type of the template of
        data["dst_type"] = template_types["FILE"]
        data["event_type"] = "EVENT_READ"
        data["time"] = get_average(time_stamps)
        data["attr"] = get_encoded_string(
            get_common_filepath(temp_holder))  # Base64

        return_sequence.append((src, template_id, data))

        history = open(history_holder, 'a')
        history.write(string_representation_of_template_instance(
            temp_holder, template_id))
        history.close()
    else:
        for i in range(length):
            return_sequence.append(sequence[i])

    # print("Compression Ratio: {}".format(len(return_sequence)/length))
    return return_sequence


def match_socket_pattern(sequence, socket_templates, malicious_templates, history_holder):
    length = len(sequence)
    print("Match socket pattern called with: {}".format(len(sequence)))
    idx = 0
    return_sequence = list()
    network_socket_holder = list()

    for edge in sequence:
        
        src = edge[0]
        dst = edge[1]
        dst_type = edge[2]["dst_type"]
        
        if dst_type == 8:
            network_socket_holder.append(edge)
        else:
            return_sequence.append(edge)


    #print("Calling process sockets with : {}".format(len(network_socket_holder)))
    temp = process_sockets(network_socket_holder, socket_templates, malicious_templates, history_holder)
    #print("After processing length: {}".format(len(temp)))
    return_sequence.extend(temp)
    return return_sequence


def summarize(templates, sorted_order, graph, process_nodes, history_file, debug=False):
    summarized_graph = nx.MultiDiGraph()
    # Clearing the previous history file
    history = open(history_file, 'w')
    history.close()
    # Clearing ends
    for node in process_nodes:
        outgoing_edges = graph.out_edges(node, data=True)
        list_of_outgoing_edges = list(outgoing_edges)
        if len(list_of_outgoing_edges) == 0:
            continue
        sorted_list_of_outgoing_edges = sorted(
            list_of_outgoing_edges, key=lambda x: x[2]['time'])
        temp_list = list(sorted_list_of_outgoing_edges)
        # Reminder: Sorted order is a list
        for template_key in sorted_order:
            actual_template = templates[template_key[0]]

            compressed_list_of_outgoing_edges = match_file_pattern(
                temp_list, actual_template, template_key[0], history_file)

            temp_list = list(compressed_list_of_outgoing_edges)

        for edge in temp_list:
            summarized_graph.add_edges_from([(edge[0], edge[1], edge[2])])

    return summarized_graph


def original_summarize(templates, sorted_order, graph, process_nodes, history_file, debug=False):
    summarized_graph = nx.MultiDiGraph()
    # Clearing the previous history file
    history = open(history_file, 'w')
    history.close()
    # Clearing ends
    for node in process_nodes:
        outgoing_edges = graph.out_edges(node, data=True)
        list_of_outgoing_edges = list(outgoing_edges)
        if len(list_of_outgoing_edges) == 0:
            continue

        temp_list = list(list_of_outgoing_edges)
        for template_key in sorted_order:
            actual_template = templates[template_key[0]]
            compressed_list_of_outgoing_edges = original_match_file_pattern(
                temp_list, actual_template, template_key[0], history_file)
            temp_list = list(compressed_list_of_outgoing_edges)

        for edge in temp_list:
            summarized_graph.add_edges_from([(edge[0], edge[1], edge[2])])

    return summarized_graph


def socket_summarize(graph, process_nodes, history_file, socket_template_file, debug=False):
    malicious_templates = dict()
    socket_templates = dict()
    summarized_graph = nx.MultiDiGraph()
    # Clearing the previous history file
    history = open(history_file, 'w')
    history.close()
    # Clearing ends
    for node in process_nodes:
        print(node)
        outgoing_edges = graph.out_edges(node, data=True)
        list_of_outgoing_edges = list(outgoing_edges)
        if len(list_of_outgoing_edges) == 0:
            continue
        
        #print("Sorting")
        sorted_list_of_outgoing_edges = sorted(
            list_of_outgoing_edges, key=lambda x: x[2]['time'])

        temp_list = match_socket_pattern(
            sorted_list_of_outgoing_edges, socket_templates, malicious_templates, history_file)
        print("Temp list length: {}".format(len(temp_list)))
        for edge in temp_list:
            summarized_graph.add_edges_from([(edge[0], edge[1], edge[2])])

    st = open(socket_template_file, 'w')
    json.dump(socket_templates, st)
    st.close()

    mt = open('malicious_socket_templates_0.json', 'w')
    json.dump(malicious_templates, mt)
    mt.close()

    return summarized_graph


def print_statistics(pruned_graph, summarized_graph):
    pruned_node_count = pruned_graph.number_of_nodes()
    summarized_node_count = summarized_graph.number_of_nodes()
    if pruned_node_count != 0:
        print("Summarized / Pruned node count ratio: {}".format(summarized_node_count/pruned_node_count))
    else:
        print("Pruned node count is 0.")

    pruned_edge_count = pruned_graph.number_of_edges()
    summarized_edge_count = summarized_graph.number_of_edges()
    if pruned_node_count != 0:
        print("Summarized / Pruned edge count ratio: {}".format(summarized_edge_count/pruned_edge_count))
    else:
        print("Pruned edge count is 0.")


def learn_or_load_then_summarize(graph_file, index_file, ridx_file, database_type, learn_templates, use_templates, template_dictionary, template_history, version):
    if version == 0 or version == 1:
        get_indices(index_file, ridx_file)
        pruned_graph = get_and_prune_the_input_graph(graph_file)
        print("Pruned Graph Loaded.")
        timestamp_map = get_timestamp_map(pruned_graph)
        print("Timestamp Map Loaded.")

        if database_type == CADET:
            psql_connection_url = 'postgresql+pg8000://cpsc538p:12345678@localhost/darpa_tc3_cadets'
        elif database_type == THEIA:
            psql_connection_url = 'postgresql+pg8000://cpsc538p:12345678@localhost/darpa_tc3_theia'
        else:
            print("Database not specified. Exiting now.")
            exit(8)

        engine = create_engine(psql_connection_url)
        Session = sessionmaker(bind=engine)
        session = Session()

        read_only_status = get_read_only_status(session)
        print("Read Only Status Loaded")

        if learn_templates:
            templates = learn_rof_templates(
                read_only_status, timestamp_map, pruned_graph, debug_info=False)
            json.dump(templates, open(template_dictionary, 'w'))
            sorted_templates = get_template_order(templates)
            print("Template Learned.")

        elif use_templates:

            loaded_templates = json.load(open(template_dictionary, 'r'))
            templates = dict()

            for key in loaded_templates:
                template_id_from_key = int(key)
                template_list = loaded_templates[key]
                t_list = list()
                for item in template_list:
                    t_list.append(int(item))
                templates[template_id_from_key] = t_list

            sorted_templates = get_template_order(templates)
            print(templates)
            print("Template Loaded.")

        print("Template Ready.")
        pruned_node_set = pruned_graph.nodes()
        process_nodes = [
            node for node in pruned_node_set if reverse_idx[str(node)][0] == 4]
        print("Starting Summarization.")
        summarized_graph = summarize(
            templates, sorted_templates, pruned_graph, process_nodes, template_history, debug=False)
        print("Summarization Complete.")
        print_statistics(pruned_graph, summarized_graph)
        summary_graph_filename = os.path.splitext(
            graph_file)[0]+"_summary_v"+str(v)+".edgelist"
        nx.write_edgelist(summarized_graph, summary_graph_filename, data=True)
        print("Wrapped up. Exiting.")
    elif version == 2:
        # This is socket version
        get_indices(index_file, ridx_file)
        pruned_graph = get_and_prune_the_input_graph(graph_file)
        print("Pruned Graph Loaded.")
        pruned_node_set = pruned_graph.nodes()
        process_nodes = []
        for node in pruned_node_set:
            if node in reverse_idx and reverse_idx[str(node)][0] == 4:
                process_nodes.append(node)
        print("Process Nodes Isolated.")
        print("Starting Summarization.")
        summarized_graph = socket_summarize(
            pruned_graph, process_nodes, template_history, template_dictionary, debug=False)
        print("Summarization Complete.")
        print_statistics(pruned_graph, summarized_graph)
        summary_graph_filename = os.path.splitext(
            graph_file)[0]+"_summary_v"+str(v)+".edgelist"
        nx.write_edgelist(summarized_graph, summary_graph_filename, data=True)
        print("Wrapped up. Exiting.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        prog='nodemerge-summarizer', description="Nodemerge Implementation (CCS 2018)")
    parser.add_argument('graph_filename')
    parser.add_argument('--learn-templates', action='store_true')
    parser.add_argument('--use-templates', action='store_true')
    parser.add_argument('-th', '--template-history',
                        help='Json file that contains the list of the templates used in summarization.')
    parser.add_argument('-td', '--template-dict',
                        help='Json file that contains the template dictionary')
    parser.add_argument('-idx', '--index-file',
                        help='Location of the index file to reduce computation time.')
    parser.add_argument('-ridx', '--reverse-index-file',
                        help='Loaction of the reverse index file to reduce computation time.')
    parser.add_argument('-cfg', '--config-file',
                        help='Json file that holds all the configuration information. If you dont have index or reverse index info, you must add the config file location where it is listed.')  # Config parser is still to be implemented
    parser.add_argument('--cadets', action='store_true')
    # Note that this should be removed in later version in favor of list based parsing so that more db can be added without trouble
    parser.add_argument('--theia', action='store_true')
    parser.add_argument('--version')

    args = parser.parse_args()

    graph_filename = args.graph_filename
    learn_template = args.learn_templates
    use_template = args.use_templates
    config_file = args.config_file
    index_file = args.index_file
    reverse_index_file = args.reverse_index_file
    is_cadet = args.cadets
    is_theia = args.theia
    is_theia = args.theia
    v = int(args.version)

    if index_file is None and reverse_index_file is None:
        if config_file is None:
            print("No index and reverse index file provided. Please specify the config file which contains the information.")
            exit(4)
    else:
        if config_file is None:
            if index_file is None and reverse_index_file is not None:
                print("Missing index file location. Please specify that in the command line or just the use the config file for all operations.")
                exit(5)
            elif index_file is not None and reverse_index_file is None:
                print("Reverse index file location is missing. Please specify that in the command line or just use the config file for all operations.")
                exit(6)

    template_history_file = args.template_history
    template_dictionary_file = args.template_dict
    if template_history_file is None:
        print("Please provide the absolute file path of the sorted templates.")
        exit(2)
    if template_dictionary_file is None:
        print("Please provide the absoluet file path of the templated dictionary.")
        exit(3)

    if learn_template and not use_template:
        # do some staff
        if is_cadet:
            learn_or_load_then_summarize(graph_filename, index_file, reverse_index_file,
                                         CADET, True, False, template_dictionary_file, template_history_file, version=v)
        elif is_theia:
            learn_or_load_then_summarize(graph_filename, index_file, reverse_index_file,
                                         THEIA, True, False, template_dictionary_file, template_history_file, version=v)
        else:
            print("Not sure which database to use. Exiting now")
            exit(20)

    elif use_template and not learn_template:
        if is_cadet:
            learn_or_load_then_summarize(graph_filename, index_file, reverse_index_file,
                                         CADET, False, True, template_dictionary_file, template_history_file, version=v)
        elif is_theia:
            learn_or_load_then_summarize(graph_filename, index_file, reverse_index_file,
                                         THEIA, False, True, template_dictionary_file, template_history_file, version=v)
        else:
            print("Not sure which database to use. Exiting now")
            exit(21)
    else:
        print("Use template is {} while learn template is {}".format(
            use_template, learn_template))
        exit(1)
