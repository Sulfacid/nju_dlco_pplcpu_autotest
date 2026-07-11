import os
import subprocess
import re
import xml.etree.ElementTree

# CPU 主要电路文件路径
CPU_CIRC = "./lab8.4.circ"

# 是否启用 RAM 预加载（用于测试需要加载 RAM 数据的样例）
# 如果不使用 RAM 预加载，则无需对电路做 RPL 适配，效率更高。
RPL = True
RPL_CIRC = "./rpl.circ"           # RAM 预加载模块文件路径

TESTCASES_PATH = './testcase/'    # 存放测试用例的目录

# 如果使用 Logisim 可执行文件，设为 True；如果使用 jar 包，设为 False
LOGISIM_EXE_OR_JAR = False
LOGISIM_PATH = "./logisim.jar"    # Logisim ITA 可执行文件或 jar 的路径

LOG = False                       # 是否输出调试日志

def run_circ(forced=True):
    """
    启动 Logisim 仿真并返回最后一行输出结果。

    参数 forced 表示是否在出现 stderr 时仍然抛出异常；
    如果 forced=False，则遇到错误时返回 None。
    """
    if LOGISIM_EXE_OR_JAR:
        cmd = [LOGISIM_PATH, CPU_CIRC, "-tty", "table"]
    else:
        cmd = ["java", "-jar", LOGISIM_PATH, CPU_CIRC, "-tty", "table"]
    if LOG:
        print("正在执行命令：", ' '.join(cmd))

    result = subprocess.run(
        cmd,
        capture_output=True,   # 捕获 stdout 和 stderr
        text=True,             # 以字符串形式返回文本结果
        encoding='utf-8'       # 指定编码，避免中文乱码
    )

    if result.stderr:
        if LOG:
            print("错误信息:")
            print(result.stderr)
        if not forced:
            return None

    reslist = result.stdout.split('\n')
    while reslist and not reslist[-1]:
        del reslist[-1]
    return reslist[-1] if reslist else None

def load_testcase(testcase):
    """
    将指定测试用例的数据写入 Logisim 电路文件中的 ROM。

    主要工作包括：
    1. 将测试指令写入 CPU 电路文件中标签为 IR 的 ROM
    2. 如果启用了 RPL，则将 RAM 预加载数据写入 rpl.circ 中对应的 ROM
    """
    def data_from_file(filename):
        with open(filename, "r", encoding='utf-8') as f:
            lines = f.read().split('\n')
            del lines[0]  # 删除 hex 文件中的地址/格式行
            return '\n'.join(lines)

    def join_format_data(format, data):
        return "addr/data: " + format + '\n' + data

    def replace_label_contents(tree, label, format, data):
        root = tree.getroot()
        for comp in root.findall(".//comp"):
            if comp.get('name') != 'ROM':
                continue

            label_elem = comp.find("./a[@name='label']")
            if label_elem is not None and label_elem.get('val') == label:
                contents_elem = comp.find("./a[@name='contents']")
                contents_text = join_format_data(format, data)

                if contents_elem is not None:
                    contents_elem.text = contents_text
                    if LOG:
                        print(f"为 '{label}' 更新数据")
                else:
                    new_attr = xml.etree.ElementTree.Element('a', {'name': 'contents'})
                    new_attr.text = contents_text
                    comp.append(new_attr)
                    if LOG:
                        print(f"为 '{label}' 创建 contents 属性")

                return
        raise BaseException(f"未找到标签为 '{label}' 的 ROM 组件。")

    try:
        cpu_tree = xml.etree.ElementTree.parse(CPU_CIRC)
        replace_label_contents(cpu_tree, "IR", "16 32", data_from_file(testcase.case()))
        cpu_tree.write(CPU_CIRC, encoding='UTF-8', xml_declaration=True)
    except xml.etree.ElementTree.ParseError:
        raise BaseException(f"文件 '{CPU_CIRC}' 解析失败，请检查文件格式。")
    except FileNotFoundError:
        raise BaseException(f"未找到电路文件 '{CPU_CIRC}'")

    if RPL:
        try:
            rpl_tree = xml.etree.ElementTree.parse(RPL_CIRC)
            replace_label_contents(
                rpl_tree,
                "RPL_HASDATA",
                "2 1",
                '1' if testcase.has_ram_data() else '0'
            )
            if testcase.has_ram_data():
                for idx, ram_filename in enumerate(testcase.ram_data()):
                    replace_label_contents(rpl_tree, f"RPL_RAM{idx}", "16 8", data_from_file(ram_filename))
            rpl_tree.write(RPL_CIRC, encoding='UTF-8', xml_declaration=True)
        except xml.etree.ElementTree.ParseError:
            raise BaseException(f"文件 '{RPL_CIRC}' 解析失败，请检查文件格式。")
        except FileNotFoundError:
            raise BaseException(f"未找到电路文件 '{RPL_CIRC}'")

class TestCase:
    def __init__(self, name, case, ram_data = None):
        self.__name = name
        self.__case_file = case
        if ram_data is not None:
            self.__ram_data_file = ram_data.copy()
            self.__has_ram_data = True
        else:
            self.__ram_data_file = [None] * 4
            self.__has_ram_data = False
    
    def name(self):
        """
        返回该 testcase 的名称
        """
        return self.__name
    
    def case(self):
        """
        返回该 testcase 的文件路径
        """
        return self.__case_file
    
    def has_ram_data(self):
        """
        该 testcase 是否需要载入 ram0~ram3 数据
        """
        return self.__has_ram_data
    
    def ram_data(self):
        """
        返回包含该 testcase 中 ram0~ram3 的数据文件路径的列表
        """
        assert self.has_ram_data()
        return self.__ram_data_file
    
    def __repr__(self):
        if self.has_ram_data():
            return f"TestCase{self.__name, self.__case_file, self.__ram_data_file}"
        return f"TestCase{self.__name, self.__case_file}"


def testcases():
    """
    扫描测试用例目录，返回所有测试用例的列表。

    支持两种文件类型：
    - `rv32ui-p-<name>.hex`：仅包含指令数据
    - `rv32ui-p-<name>_d.hex0/hex1/hex2/hex3`：包含 RAM 预加载数据
    """
    cases_raw = {}
    all_entries = os.listdir(TESTCASES_PATH)
    files = [f for f in all_entries if os.path.isfile(os.path.join(TESTCASES_PATH, f))]
    hex_files = [f for f in files if f.endswith('.hex') or f.endswith('.hex0') or f.endswith('.hex1') or f.endswith('.hex2') or f.endswith('.hex3')]

    pattern = re.compile(r'^rv32ui-p-(.+)\.hex[0123]?$')
    for f in hex_files:
        match = pattern.match(f)
        assert match is not None
        key = match.group(1)
        if key.endswith("_d"):
            if key[:-2] not in cases_raw:
                cases_raw[key[:-2]] = [None] * 5
            if f[-1].isnumeric():
                cases_raw[key[:-2]][int(f[-1]) + 1] = TESTCASES_PATH + ("" if TESTCASES_PATH.endswith("/") else "/") + f
        else:
            if key not in cases_raw:
                cases_raw[key] = [None] * 5
            cases_raw[key][0] = TESTCASES_PATH + ("" if TESTCASES_PATH.endswith("/") else "/")  + f

    res = []
    for key in cases_raw:
        if cases_raw[key][1] is None:
            res.append(TestCase(key, cases_raw[key][0]))
        else:
            res.append(TestCase(key, cases_raw[key][0], cases_raw[key][1:]))

    return res


if __name__ == "__main__":
    def to_bin(bin_str):
        """
        将 Logisim 输出的二进制分段字符串转为整数。

        例如输入 "0000 0001 0101 0101"。
        """
        bin_list = bin_str.split(' ')
        section_len = len(bin_list[0])
        new_list = [int(x, 2) for x in bin_list]
        res = 0
        for idx, val in enumerate(new_list[::-1]):
            res += 2 ** (idx * section_len) * val
        return res

    tc = testcases()
    if LOG: print(tc)
    res = {}
    for idx, case in enumerate(tc):
        # if idx < 14:
        #     continue
        if LOG: print(case)
        if not RPL and case.has_ram_data():
            if LOG: print("未启用 RPL，跳过")
            continue
        load_testcase(case)
        raw = run_circ()

        if raw == None: continue
    
        raw_list = raw.split('\t')
        res[case.name()] = [to_bin(item) for item in raw_list]
        # res[case.name()][-2] = hex(res[case.name()][-2])
        # res[case.name()][-1] = hex(res[case.name()][-1])
        print('|'.join([str(idx+1), case.name()] + [str(x) for x in res[case.name()]]))
    if LOG: print(res)