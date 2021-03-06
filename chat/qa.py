# -*- coding: utf-8 -*-
# PEP 8 check with Pylint
"""qa

QA based on NLU and Dialogue scene.
基于自然语言理解和对话场景的问答。

Available functions:
- All classes and functions: 所有类和函数
"""
import sqlite3
import copy
import json
from collections import deque
from py2neo import Graph, Node, Relationship
from .config import getConfig
from .api import nlu_tuling, get_location_by_ip
from .semantic import synonym_cut, get_tag, similarity, check_swords, get_location
from .mytools import time_me, get_current_time, random_item, get_age
from .word2pinyin import pinyin_cut, jaccard_pinyin

log_do_not_know = getConfig("path", "do_not_know")
cmd_end_scene = ["退出业务场景", "退出场景", "退出", "返回", "结束", "发挥"]
# 上一步功能为通用模式
cmd_previous_step = ["上一步", "上一部", "上一页", "上一个"]
# 下一步功能通过界面按钮实现
cmd_next_step = ["下一步", "下一部", "下一页", "下一个"]
cmd_repeat = ['重复', '再来一个', '再来一遍', '你刚说什么', '再说一遍', '重来']

def get_navigation_location():
    """获取导航地点 
    """
    try:
        nav_db = getConfig("nav", "db")
        key = getConfig("nav", "key")
        db = sqlite3.connect(nav_db)
    except:
        print("导航数据库连接失败！请检查是否存在文件：" + nav_db)
        return []
    try:
        cursor = db.execute("SELECT name from " + key)
    except:
        print("导航数据库没有找到键值：" + key)
        return []
    # 过滤0记录
    names = [row[0] for row in cursor if row[0]]
    return names


class Robot():
    """NLU Robot.
    自然语言理解机器人。

    Public attributes:
    - graph: The connection of graph database. 图形数据库连接。
    - pattern: The pattern for NLU tool: 'semantic' or 'vec'. 语义标签或词向量模式。
    - memory: The context memory of robot. 机器人对话上下文记忆。
    """
    def __init__(self, password="train"):
        # 连接图知识库
        self.graph = Graph("http://localhost:7474/db/data/", password=password)
        # 语义模式：'semantic' or 'vec'
        self.pattern = 'semantic'
        # 获取导航地点数据库
        self.locations = get_navigation_location()
        # 在线场景标志，默认为False
        self.is_scene = False
        # 在线调用百度地图IP定位api，网络异常时返回默认地址：上海市/从配置信息获取
        self.address = get_location_by_ip(self.graph.find_one("User", "userid", "A0001")['city'])
        # 机器人配置信息
        self.user = None
        # 可用话题列表
        self.usertopics = []
        # 当前QA话题
        self.topic = ""
        # 当前QA id
        self.qa_id = get_current_time()
		# 短期记忆：最近问过的10个问题与10个答案
        self.qmemory = deque(maxlen=10) # 问题
        self.amemory = deque(maxlen=10) # 答案
        self.pmemory = deque(maxlen=10) # 上一步
        # 匹配不到时随机回答 TODO：记录回答不上的所有问题，
        self.do_not_know = [
            "这个问题太难了，{robotname}还在学习中",
            "这个问题{robotname}不会，要么我去问下",
            "您刚才说的是什么，可以再重复一遍吗",
            "{robotname}刚才走神了，一不小心没听清",
            "{robotname}理解的不是很清楚啦，你就换种方式表达呗",
            "不如我们换个话题吧",
            "咱们聊点别的吧",
            "{robotname}正在学习中",
            "{robotname}正在学习哦",
            "不好意思请问您可以再说一次吗",
            "额，这个问题嘛。。。",
            "{robotname}得好好想一想呢",
            "请问您说什么",
            "您问的问题好有深度呀",
            "{robotname}没有听明白，您能再说一遍吗"
        ]

    def __str__(self):
        return "Hello! I'm {robotname} and I'm {robotage} years old.".format(**self.user)

    @time_me()
    def configure(self, info="", userid="userid"):
        """Configure knowledge base.
        配置知识库。
        """
        assert userid is not "", "The userid can not be empty!"
        # TO UPGRADE 对传入的userid参数分析，若不合适则报相应消息 2017-6-7
        if userid != "A0001":
            userid = "A0001"
            print("userid 不是标准A0001，已经更改为A0001")
        match_string = "MATCH (config:Config) RETURN config.name as name"
        subgraphs = [item[0] for item in self.graph.run(match_string)]
        print("所有知识库：", subgraphs)
        if not info:
            config = {"databases": []}
            match_string = "MATCH (user:User)-[r:has]->(config:Config)" + \
                "where user.userid='" + userid + \
                "' RETURN config.name as name, r.bselected as bselected, r.available as available"
            for item in self.graph.run(match_string):
                config["databases"].append(dict(name=item[0], bselected=item[1], available=item[2]))
            print("可配置信息：", config)
            return config
        else:
            selected_names = info.split()
        forbidden_names = list(set(subgraphs).difference(set(selected_names)))
        print("选中知识库：", selected_names)
        print("禁用知识库：", forbidden_names)
        # TODO：待合并精简
        for name in selected_names:
            match_string = "MATCH (user:User)-[r:has]->(config:Config) where user.userid='" \
                + userid + "' AND config.name='" + name + "' SET r.bselected=1"
            # print(match_string)
            self.graph.run(match_string)
        for name in forbidden_names:
            match_string = "MATCH (user:User)-[r:has]->(config:Config) where user.userid='" \
                + userid + "' AND config.name='" + name + "' SET r.bselected=0"
            # print(match_string)
            self.graph.run(match_string)
        return self.get_usertopics(userid=userid)

    # @time_me()
    def get_usertopics(self, userid="A0001"):
        """Get usertopics list.
        """
        usertopics = []
        if not userid:
            userid = "A0001"
        # 从知识库获取用户拥有权限的子知识库列表
        match_string = "MATCH (user:User)-[r:has {bselected:1, available:1}]->(config:Config)" + \
            "where user.userid='" + userid + "' RETURN config"
        data = self.graph.run(match_string).data()
        for item in data:
            usertopics.extend(item["config"]["topic"].split(","))
        print("用户：", userid, "\n已有知识库列表：", usertopics)
        return usertopics

    def iformat(self, sentence):
        """Individualization of robot answer.
        个性化机器人回答。
        """
        return sentence.format(**self.user)

    # @time_me()
    def add_to_memory(self, question="question", userid="userid"):
        """Add user question to memory.
        将用户当前对话加入信息记忆。

        Args:
            question: 用户问题。
                Defaults to "question".
            userid: 用户唯一标识。
                Defaults to "userid".
        """
        previous_node = self.graph.find_one("Memory", "qa_id", self.qa_id)
        self.qa_id = get_current_time()
        node = Node("Memory", question=question, userid=userid, qa_id=self.qa_id)
        if previous_node:
            relation = Relationship(previous_node, "next", node)
            self.graph.create(relation)
        else:
            self.graph.create(node)

    # Development requirements from Mr Tang in 2017-5-11.
    # 由模糊匹配->全匹配 from Mr Tang in 2017-6-1.
    def extract_navigation(self, question):
        """Extract navigation。抽取导航地点。
        QA匹配模式：从导航地点列表选取匹配度最高的地点。

        Args:
            question: User question. 用户问题。
        """
        result = dict(question=question, name='', content=self.iformat(random_item(self.do_not_know)), \
            context="", tid="", url="", behavior=0, parameter="", txt="", img="", button="", valid=1)
        # temp_sim = 0
        # sv1 = synonym_cut(question, 'wf')
        # if not sv1:
            # return result
        for location in self.locations:
            # 判断“去”和地址关键词是就近的动词短语情况
            keyword = "去" + location
            if keyword in question:
                print("Original navigation")
                result["name"] = keyword
                result["content"] = location
                result["context"] = "user_navigation"
                result["behavior"] = int("0x001B", 16)
                return result
            # sv2 = synonym_cut(location, 'wf')
            # if sv2:
                # temp_sim = similarity(sv1, sv2, 'j')
            # 匹配加速，不必选取最高相似度，只要达到阈值就终止匹配
            # if temp_sim > 0.92:
                # print("Navigation location: " + location + " Similarity Score: " + str(temp_sim))
                # result["content"] = location
                # result["context"] = "user_navigation"
                # result["behavior"] = int("0x001B", 16)
                # return result
        return result

    def extract_pinyin(self, question, subgraph):
        """Extract synonymous QA in NLU database。
        QA匹配模式：从图形数据库选取匹配度最高的问答对。

        Args:
            question: User question. 用户问题。
            subgraph: Sub graphs corresponding to the current dialogue. 当前对话领域对应的子图。
        """
        temp_sim = 0
        result = dict(question=question, name='', content=self.iformat(random_item(self.do_not_know)), \
            context="", tid="", url="", behavior=0, parameter="", txt="", img="", button="", valid=1)
        sv1 = pinyin_cut(question)
        print(sv1)
        for node in subgraph:
            iquestion = self.iformat(node["name"])
            sv2 = pinyin_cut(iquestion)
            print("  ", sv2)
            temp_sim = jaccard_pinyin(sv1, sv2)
            print(temp_sim)
            # 匹配加速，不必选取最高相似度，只要达到阈值就终止匹配
            if temp_sim > 0.75:
                print("Q: " + iquestion + " Similarity Score: " + str(temp_sim))
                result['name'] = iquestion
                result["content"] = self.iformat(random_item(node["content"].split("|")))
                result["context"] = node["topic"]
                result["tid"] = node["tid"]
                result["txt"] = node["txt"]
                result["img"] = node["img"]
                result["button"] = node["button"]
                if node["url"]:
                    result["url"] = random_item(node["url"].split("|"))
                if node["behavior"]:
                    result["behavior"] = int(node["behavior"], 16)
                if node["parameter"]:
                    result["parameter"] = node["parameter"]
                func = node["api"]
                if func:
                    exec("result['content'] = " + func + "('" + result["content"] + "')")
                return result
        return result

    def extract_synonym(self, question, subgraph):
        """Extract synonymous QA in NLU database。
        QA匹配模式：从知识库选取匹配度最高的问答对。

        Args:
            question: User question. 用户问题。
            subgraph: Sub graphs corresponding to the current dialogue. 当前对话领域对应的子图。
        """
        temp_sim = 0
        result = dict(question=question, name='', content=self.iformat(random_item(self.do_not_know)), \
            context="", tid="", url="", behavior=0, parameter="", txt="", img="", button="", valid=1)
	    # semantic: 切分为同义词标签向量，根据标签相似性计算相似度矩阵，再由相似性矩阵计算句子相似度
	    # vec: 切分为词向量，根据词向量计算相似度矩阵，再由相似性矩阵计算句子相似度
        if self.pattern == 'semantic':
        # elif self.pattern == 'vec':
            sv1 = synonym_cut(question, 'wf')
            if not sv1:
                return result
            for node in subgraph:
                iquestion = self.iformat(node["name"])
                if question == iquestion:
                    print("Similarity Score: Original sentence")
                    result['name'] = iquestion
                    result["content"] = self.iformat(random_item(node["content"].split("|")))
                    result["context"] = node["topic"]
                    result["tid"] = node["tid"]
                    result["txt"] = node["txt"]
                    result["img"] = node["img"]
                    result["button"] = node["button"]
                    if node["url"]:
                        result["url"] = random_item(node["url"].split("|"))
                    if node["behavior"]:
                        result["behavior"] = int(node["behavior"], 16)
                    if node["parameter"]:
                        result["parameter"] = node["parameter"]
                    # 知识实体节点api抽取原始问题中的关键信息，据此本地查询/在线调用第三方api/在线爬取
                    func = node["api"]
                    if func:
                        exec("result['content'] = " + func + "('" + result["content"] + "')")
                    return result
                sv2 = synonym_cut(iquestion, 'wf')
                if sv2:
                    temp_sim = similarity(sv1, sv2, 'j')
			    # 匹配加速，不必选取最高相似度，只要达到阈值就终止匹配
                if temp_sim > 0.92:
                    print("Q: " + iquestion + " Similarity Score: " + str(temp_sim))
                    result['name'] = iquestion
                    result["content"] = self.iformat(random_item(node["content"].split("|")))
                    result["context"] = node["topic"]
                    result["tid"] = node["tid"]
                    result["txt"] = node["txt"]
                    result["img"] = node["img"]
                    result["button"] = node["button"]
                    if node["url"]:
                        result["url"] = random_item(node["url"].split("|"))
                    if node["behavior"]:
                        result["behavior"] = int(node["behavior"], 16)
                    if node["parameter"]:
                        result["parameter"] = node["parameter"]
                    func = node["api"]
                    if func:
                        exec("result['content'] = " + func + "('" + result["content"] + "')")
                    return result
        return result

    def extract_keysentence(self, question, data=None):
        """Extract keysentence QA in NLU database。
        QA匹配模式：从知识库选取包含关键句的问答对。

        Args:
            question: User question. 用户问题。
        """
        result = dict(question=question, name="", content=self.iformat(random_item(self.do_not_know)), \
            context="", tid="", url="", behavior=0, parameter="", txt="", img="", button="", valid=1)
        # if data:
            # subgraph = [node for node in data if node["name"] in question]
            # TODO：从包含关键句的问答对中选取和当前问答的跳转链接最接近的
            # node = 和当前问答的跳转链接最接近的 in subgraph
        usertopics = ' '.join(self.usertopics)
        # 只从目前挂接的知识库中匹配
        match_string = "MATCH (n:NluCell) WHERE '" + question + \
            "' CONTAINS n.name and '" + usertopics +  \
            "' CONTAINS n.topic RETURN n LIMIT 1"
        subgraph = self.graph.run(match_string).data()
        if subgraph:
            # TODO：判断 subgraph 中是否包含场景根节点
            node = list(subgraph)[0]['n']
            print("Similarity Score: Key sentence")
            result['name'] = node['name']
            result["content"] = self.iformat(random_item(node["content"].split("|")))
            result["context"] = node["topic"]
            result["tid"] = node["tid"]
            result["txt"] = node["txt"]
            result["img"] = node["img"]
            result["button"] = node["button"]
            if node["url"]:
                result["url"] = random_item(node["url"].split("|"))
            if node["behavior"]:
                result["behavior"] = int(node["behavior"], 16)
            if node["parameter"]:
                result["parameter"] = node["parameter"]
            # 知识实体节点api抽取原始问题中的关键信息，据此本地查询/在线调用第三方api/在线爬取
            func = node["api"]
            if func:
                exec("result['content'] = " + func + "('" + result["content"] + "')")
            return result
        return result

    def remove_name(self, question):
        # 姓氏误匹配重定义
        if question.startswith("小") and len(question) == 2:
            question = self.user['robotname']
        # 称呼过滤
        for robotname in ["小民", "小明", "小名", "晓明"]:
            if question.startswith(robotname) and len(question) >= 4 and "在线" not in question:
                question = question.lstrip(robotname)
        if not question:
            question = self.user['robotname']
        return question

    @time_me()
    def search(self, question="question", tid="", userid="userid"):
        """Nlu search. 语义搜索。

        Args:
            question: 用户问题。
                Defaults to "question".
            userid: 用户唯一标识。
                Defaults to "userid"

        Returns:
            Dict contains:
            question, answer, topic, tid, url, behavior, parameter, txt, img, button.
            返回包含问题，答案，话题，资源，行为，动作，文本，图片及按钮的字典。
        """
        # 添加到问题记忆
        # self.qmemory.append(question)
        # self.add_to_memory(question, userid)

        # 语义：场景+全图+用户配置模式（用户根据 userid 动态获取其配置信息）
        # ========================初始化配置信息==========================
        self.user = self.graph.find_one("User", "userid", userid)
        self.usertopics = self.get_usertopics(userid=userid)
        do_not_know = dict(
            question=question,
            name="",
            # content=self.iformat(random_item(self.do_not_know)),
            content="",
            context="",
            tid="",
            url="",
            behavior=0,
            parameter="",
            txt="",
            img="",
            button="",
            valid=1)
        error_page = dict(
            question=question,
            name="",
            content=self.user['error_page'],
            context="",
            tid="",
            url="",
            behavior=int("0x1500", 16), # Modify：场景内 behavior 统一为 0x1500。(2018-1-8)
            parameter="",
            txt="",
            img="",
            button="",
            valid=0)

        # ========================一、预处理=============================
        # 问题过滤(添加敏感词过滤 2017-5-25)
        if check_swords(question):
            print("问题包含敏感词！")
            return do_not_know
        # 移除称呼
        question = self.remove_name(question)

        # ========================二、导航===============================
        result = self.extract_navigation(question)
        if result["context"] == "user_navigation":
            self.amemory.append(result) # 添加到普通记忆
            self.pmemory.append(result)
            return result
        
        # ========================三、语义场景===========================
        result = copy.deepcopy(do_not_know)
        
        # 全局上下文——重复
        for item in cmd_repeat:
            # TODO：确认返回的是正确的指令而不是例如唱歌时的结束语“可以了”
            # TODO：从记忆里选取最近的有意义行为作为重复的内容
            if item == question:
                if self.amemory:
                    return self.amemory[-1]
                else:
                    return do_not_know

        # 场景——退出
        for item in cmd_end_scene:
            if item == question: # 完全匹配退出模式
                # result['behavior'] = int("0x0020", 16)
                result['behavior'] = 0
                result['name'] = '退出'
                # result['content'] = "好的，退出"
                result['content'] = ""
                self.is_scene = False
                self.topic = ""
                self.amemory.clear() # 清空场景记忆
                self.pmemory.clear() # 清空场景上一步记忆
                return result

        # 场景——上一步：使用双向队列实现
        if self.is_scene:
            for item in cmd_previous_step:
                if item in question:
                    # 添加了链接跳转判断（采用该方案 2017-12-22）
                    if len(self.pmemory) > 1:
                        self.amemory.pop()
                        return self.pmemory.pop()
                    elif len(self.pmemory) == 1:
                        return self.pmemory[-1]
                    else:
                        # Modify：返回 error_page 2017-12-22
                        return error_page
                        # return do_not_know
                    # 未添加链接跳转判断（不用该方案 2017-12-22）
                    # if len(self.pmemory) > 1:
                        # return self.amemory.pop()
                    # elif len(self.amemory) == 1:
                        # return self.amemory[-1]
                    # else:
                        # return do_not_know
            # 场景——下一步：使用双向队列实现
            for item in cmd_next_step:
                if item in question:
                    if len(self.amemory) >= 1:
                        cur_button = json.loads(self.amemory[-1]['button']) if self.amemory[-1]['button'] else {}
                        next = cur_button.get('next', {})
                        if next:
                            next_tid = next['url']
                            next_question = next['content']
                            match_string = "MATCH (n:NluCell {name:'" + \
                                next_question + "', topic:'" + self.topic + \
                                "', tid:" + next_tid + "}) RETURN n"
                            match_data = list(self.graph.run(match_string).data())
                            if match_data:
                                node = match_data[0]['n']
                                result['name'] = self.iformat(node["name"])
                                result["content"] = self.iformat(random_item(node["content"].split("|")))
                                result["context"] = node["topic"]
                                result["tid"] = node["tid"]
                                result["txt"] = node["txt"]
                                result["img"] = node["img"]
                                result["button"] = node["button"]
                                if node["url"]:
                                    result["url"] = random_item(node["url"].split("|"))
                                if node["behavior"]:
                                    result["behavior"] = int(node["behavior"], 16)
                                if node["parameter"]:
                                    result["parameter"] = node["parameter"]
                                func = node["api"]
                                if func:
                                    exec("result['content'] = " + func + "('" + result["content"] + "')")
                                # 添加到场景记忆
                                self.pmemory.append(self.amemory[-1])
                                self.amemory.append(result)
                                return result
                    return error_page
          
        # ==========================场景匹配=============================
        tag = get_tag(question, self.user)
        # subgraph_all = list(self.graph.find("NluCell", "tag", tag)) # 列表
        subgraph_all = self.graph.find("NluCell", "tag", tag) # 迭代器
        usergraph_all = [node for node in subgraph_all if node["topic"] in self.usertopics]
        usergraph_scene = [node for node in usergraph_all if node["topic"] == self.topic]
       
        if self.is_scene: # 在场景中：语义模式+关键句模式
            if usergraph_scene:
                result = self.extract_synonym(question, usergraph_scene)
                if not result["context"]:
                    result = self.extract_keysentence(question, usergraph_scene)
                # result = self.extract_pinyin(question, usergraph_scene)
                if result["context"]:
                    print("在场景中，匹配到场景问答对")
                    # 检测结果的 tid 是否是当前场景的子场景跳转链接
                    # 实现：在 self.amemory[-1] 的跳转链接集合中查找匹配的 tid
                    # ===================================================
                    data_img = json.loads(self.amemory[-1]['img']) if self.amemory[-1]['img'] else {}
                    data_button = json.loads(self.amemory[-1]['button']) if self.amemory[-1]['button'] else {}
                    def get_tids(data):
                        tids = set()
                        for key in data.keys():
                            tid = data[key]['url']
                            if tid:
                                tids.add(int(tid))
                        return tids
                    pre_tids = get_tids(data_img).union(get_tids(data_button.setdefault('area', {})))
                    if int(result["tid"]) in pre_tids:
                        print("正确匹配到当前场景的子场景")
                        self.pmemory.append(self.amemory[-1])
                        self.amemory.append(result) # 添加到场景记忆
                        return result
                    # ===================================================
            # 场景中若找不到子图或者匹配不到就重复当前问题->返回自定义错误提示
            # Modify：返回 error_page (2017-12-22)
            # if self.amemory:              
                # return self.amemory[-1]
            # else:
                # return error_page
            return error_page

        else: # 不在场景中：语义模式+关键句模式
            result = self.extract_synonym(question, usergraph_all)
            if not result["context"]:
                result = self.extract_keysentence(question)
            # result = self.extract_pinyin(question, usergraph_all)         
            if result["tid"] != '': # 匹配到场景节点
                if int(result["tid"]) == 0:
                    print("不在场景中，匹配到场景根节点")
                    self.is_scene = True # 进入场景
                    self.topic = result["context"]
                    self.amemory.clear() # 进入场景前清空普通记忆
                    self.pmemory.clear()
                    self.amemory.append(result) # 添加到场景记忆
                    self.pmemory.append(result)
                    return result
                else:
                    print("不在场景中，匹配到场景子节点")
                    return do_not_know
            elif result["context"]: # 匹配到普通节点
                self.topic = result["context"]
                self.amemory.append(result) # 添加到普通记忆
                self.pmemory.append(result)
                return result

        # ========================五、在线语义===========================
        if not self.topic:
            # 1.音乐(唱一首xxx的xxx)
            if "唱一首" in question or "唱首" in question or "我想听" in question:
                result["behavior"] = int("0x0001", 16)
                result["content"] = "好的，正在准备哦"
            # 2.附近有什么好吃的
            elif "附近" in question or "好吃的" in question:
                result["behavior"] = int("0x001C", 16)
                result["content"] = self.address
            # 3.nlu_tuling(天气)
            elif "天气" in question:
                # 图灵API变更之后 Add in 2017-8-4
                location = get_location(question)
                if not location:
                    # 问句中不包含地址
                    weather = nlu_tuling(self.address + question)
                else:
                    # 问句中包含地址
                    weather = nlu_tuling(question)
                # 图灵API变更之前    
                # weather = nlu_tuling(question, loc=self.address)
                result["behavior"] = int("0x0000", 16)
                try:
                    # 图灵API变更之前
                    temp = weather.split(";")[0].split(",")[1].split()
                    myweather = temp[0] + temp[2] + temp[3]

                    # 图灵API变更之后 Add in 2017-8-3
                    # temp = weather.split(",")
                    # myweather = temp[1] + temp[2]
                except:
                    myweather = weather
                result["content"] = myweather
                result["context"] = "nlu_tuling"
            # 4.追加记录回答不上的所有问题
            else:
                with open(log_do_not_know, "a", encoding="UTF-8") as file:
                    file.write(question + "\n")
            # 5.nlu_tuling
            # else:
                # result["content"] = nlu_tuling(question, loc=self.address)
                # result["context"] = "nlu_tuling"
        if result["context"]: # 匹配到在线语义
            self.amemory.append(result) # 添加到普通记忆
        # ==============================================================

        return result
