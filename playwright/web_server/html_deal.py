import copy
import re

from bs4 import BeautifulSoup, NavigableString, Tag, element
def process_special_tags(tag: Tag) -> str:
    """处理混合标签的文本内容"""
    result = []
    for elem in tag.descendants:
        if isinstance(elem, NavigableString):
            text = elem.strip()
            if text:
                result.append(text)
        elif isinstance(elem, Tag):
            # 处理特殊标记
            if elem.name == "span" and "ref_content_circle" in elem.get("class", []):
                ref_text = elem.get_text(strip=True)
                if ref_text:
                    result.append(f"[{ref_text}]")
            # 处理加粗标记
            elif elem.name == "strong":
                strong_text = elem.get_text(strip=True)
                if strong_text:
                    result.append(strong_text)

    return " ".join(result).strip()


def extract_list_items(ul_tag: Tag) -> list:
    """增强列表项处理逻辑"""
    items = []
    for li in ul_tag.find_all("li", recursive=False):
        # 获取完整文本内容，保留空白符
        full_text = li.get_text(separator=" ", strip=True)

        # 移除开头的序号标记（如"• "）
        if full_text.startswith("• "):
            full_text = full_text[2:]

        # 处理特殊标记（如引用标记）
        if full_text:
            # 特殊标记处理逻辑
            processed_text = process_special_tags(li)
            items.append(processed_text or full_text)

    return items


def zhipu_parse_html(content: str) -> str:
    try:
        soup = BeautifulSoup(content, "html.parser")
        result = []

        # 使用更精确的选择器
        containers = soup.select("div.w-full.flex.flex-col.relative")

        for container in containers:
            # 使用CSS选择器直接定位目标元素
            for p in container.select("p.svelte-121hp7c"):
                text = p.get_text(strip=True)
                if text:
                    result.append(text)

            # 处理列表项
            for ul in container.select("ul[dir='auto']"):
                items = []
                for li in ul.select("li.text-start"):
                    prefix = "- "
                    # 处理特殊标记
                    strong = li.select_one("strong")
                    if strong:
                        items.append(f"{prefix}{strong.get_text(strip=True)}")
                result.extend(items)

        return "\n".join(result)

    except Exception as e:
        print(f"解析错误: {str(e)}")
        return ""


def zhipu_parse_html(content: str) -> str:
    try:
        soup = BeautifulSoup(content, "html.parser")
        result = []

        # 精准选择容器
        containers = soup.select("div#response-content-container")

        for container in containers:
            # 递归处理所有文本节点
            process_element(container, result)

        return "\n".join(result)

    except Exception as e:
        print(f"解析错误: {str(e)}")
        return ""


def process_element(element, result, level=0):
    if isinstance(element, NavigableString):
        text = element.strip()
        if text:
            result.append("  " * level + text)
    elif isinstance(element, Tag):
        # 过滤特定 class 的 div
        if element.name == "div" and "class" in element.attrs:
            classes = element.get("class", [])
            class_str = " ".join(sorted(classes))
            excluded_classes = [
                "flex flex-col gap-2",
                "mb-2 text-left text-sm text-gray-500 dark:text-gray-400",
                "relative w-full",
            ]
            if class_str in excluded_classes:
                return  # 跳过该 div 及其子节点

        # 特殊元素处理
        if element.name == "ul" and "dir" in element.attrs:
            items = extract_list_items(element)
            result.extend(items)
        elif element.name == "p" and "svelte-121hp7c" in element.get("class", []):
            paragraph_text = element.get_text(strip=True)
            if paragraph_text:
                result.append(paragraph_text)

        # 递归处理子节点
        for child in element.children:
            process_element(child, result, level + 1)


def _extract_paragraph(tag: Tag) -> str:
    """提取段落文本"""
    return _extract_text_recursive(tag)


def _extract_list_items(ul_tag: Tag) -> list:
    items = []
    list_type = ul_tag.name  # 'ul' or 'ol'

    for i, li in enumerate(ul_tag.find_all("li", recursive=False)):
        # 创建 li 的深拷贝以避免修改原始文档
        li_copy = copy.copy(li)

        # 移除所有 a 标签
        for a in li_copy.find_all("a", recursive=True):
            a.decompose()

        item_text = _extract_text_recursive(li_copy)
        if item_text:
            prefix = f"{i+1}. " if list_type == "ol" else "- "
            items.append(f"{prefix}{item_text}")

    return items


def _extract_text_recursive(tag: Tag) -> str:
    result = []
    for elem in tag.children:
        if isinstance(elem, NavigableString):
            stripped = elem.strip()
            if stripped:
                result.append(stripped)
        elif isinstance(elem, Tag):
            if elem.name == "a":
                continue  # 忽略 a 标签
            child_text = _extract_text_recursive(elem)
            if child_text:
                result.append(child_text)
    return " ".join(result).strip()


def process_all_lists(tag, result):
    """增强型列表处理函数"""
    # 先处理当前层级列表
    for ul in tag.find_all("ul", class_="auto-hide-last-sibling-br", recursive=False):
        list_content = process_list_with_nested(ul)
        if list_content:
            result.extend(list_content)

    # 递归处理子元素中的列表
    for child in tag.children:
        if isinstance(child, Tag):
            process_all_lists(child, result)


def process_list_with_nested(ul_tag: Tag) -> list:
    """支持多级嵌套列表处理（优化版）"""
    items = []
    is_ordered = bool(ul_tag.find_parent("ol"))

    for li in ul_tag.find_all("li", recursive=False):
        # 提取当前li内容（不含引用标记）
        content = doubao_process_list_item(li)

        if content:
            prefix = f"{len(items)+1}. " if is_ordered else "• "
            items.append(f"{prefix}{content}")

        # 递归处理子列表
        sub_lists = li.find_all("ul", class_="auto-hide-last-sibling-br", recursive=False)
        for sub_ul in sub_lists:
            sub_items = process_list_with_nested(sub_ul)
            items.extend([f"  {item}" for item in sub_items])

    return items


def doubao_parse_html_to_string(html_content: str) -> str:
    try:
        soup = BeautifulSoup(html_content, "html.parser")
        result = []

        containers = soup.find_all("div", class_="container-ZYIsnH") or soup.find_all(
            "div", class_="zone-container editor-kit-container"
        )

        if not containers:
            return "未找到有效内容容器"

        for container in containers:
            # 新增：流式处理容器内所有直接子节点
            for child in container.children:
                if isinstance(child, element.Tag):
                    # 处理标题
                    if child.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                        if "header-QFbyWT" in child.get("class", []):
                            text = child.get_text(strip=True)
                            if text:
                                result.append(f"## {text}")

                    # 处理ace-line
                    elif child.name == "div" and "ace-line" in child.get("class", []):
                        for span in child.find_all("span", attrs={"data-string": "true"}):
                            text = span.get_text(strip=True)
                            if text:
                                result.append(text)

                    # 处理段落
                    elif child.name == "div" and "paragraph-element" in child.get("class", []):
                        text_content = doubao_process_paragraph(child)
                        if text_content:
                            result.append(text_content)

                    # 处理列表
                    elif child.name == "ul" and "auto-hide-last-sibling-br" in child.get("class", []):
                        list_content = process_list_with_nested(child)
                        if list_content:
                            result.extend(list_content)

        return "\n\n".join(result)

    except Exception as e:
        return f"解析错误: {str(e)}"


def doubao_process_paragraph(tag: element.Tag) -> str:
    """增强型段落处理（移除引用标记）"""
    content = []
    for node in tag.descendants:
        if isinstance(node, element.NavigableString):
            if node.strip():
                content.append(node.strip())
        elif isinstance(node, element.Tag):
            if node.name == "strong" and node.get_text(strip=True):
                content.append(f"**{node.get_text(strip=True)}**")

    return " ".join(content)


def doubao_process_ordered_list(tag: element.Tag) -> str:
    """处理有序列表"""
    items = []
    try:
        # 修正4：使用更安全的查找方式
        for i, li in enumerate(tag.find_all("li", recursive=False), 1):
            content = doubao_process_list_item(li)
            if content:
                items.append(f"{i}. {content}")
        return "\n".join(items)
    except Exception:
        return ""


def doubao_process_unordered_list(tag: element.Tag) -> str:
    """处理无序列表"""
    items = []
    try:
        for li in tag.find_all("li", recursive=False):
            content = doubao_process_list_item(li)
            if content:
                items.append(f"• {content}")
        return "\n".join(items)
    except Exception:
        return ""


def doubao_process_list_item(li: element.Tag) -> str:
    """增强型列表项处理"""
    content = []
    # 使用深度优先遍历
    for node in li.descendants:
        if isinstance(node, element.NavigableString):
            text = node.strip()
            if text:
                content.append(text)
        elif isinstance(node, element.Tag):
            if node.name == "strong":
                strong_text = node.get_text(strip=True)
                if strong_text:
                    content.append(f"**{strong_text}**")

    return " ".join(content)


if __name__ == "__main__":
    aaa = """
<div class="doc-y97LQy">
<div class="content-xmRmZa">
<div class="zone-container editor-kit-container editor-OuwWTU first-h1-as-title-k1qiex notranslate chrome chrome88" data-zone-id="0" data-zone-container="*" data-slate-editor="true" contenteditable="false"><div class="ace-line ol-idG7IjVFHw list-div list-start-number1" data-node="true" dir="auto"><ol class="list-number1 r-list r-list-number" data-origin-start="1" start="1" data-start="1"><li style="font-weight:bold;" start="1" data-start="1"><span data-string="true" style="font-weight:bold;" data-leaf="true">少年变故，入道青云</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ol></div><div class="ace-line list-div" data-node="true" dir="auto"><ul class="list-bullet1 r-list r-list-bullet"><li><span data-string="true" data-leaf="true">通用前提：主角处于弱势背景（平凡村落、底层身份），因不可抗力的重大灾难（灭门、战争、阴谋）打破原有生活秩序，为生存或追寻真相被迫进入全新环境（修真门派、特殊组织）。</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ul></div><div class="ace-line list-div" data-node="true" dir="auto"><ul class="list-bullet1 r-list r-list-bullet"><li><span data-string="true" data-leaf="true">情节发展走向：主角以弱者姿态进入新环境，因资质、身份等问题面临边缘化，同时意外获得隐藏能力或秘密，为后续成长埋下伏笔。</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ul></div><div class="ace-line ol-idNc5Cd884 list-div" data-node="true" dir="auto"><ol class="list-number1 r-list r-list-number" data-origin-start="2" start="2" data-start="2"><li style="font-weight:bold;" start="2" data-start="2"><span data-string="true" style="font-weight:bold;" data-leaf="true">七脉会武，初露锋芒</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ol></div><div class="ace-line list-div" data-node="true" dir="auto"><ul class="list-bullet1 r-list r-list-bullet"><li><span data-string="true" data-leaf="true">通用前提：主角所在组织（门派、团体）设置竞争机制（比武、考核），主角因特殊机缘（法宝、秘籍）获得竞争优势，需在公开场合证明自身价值。</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ul></div><div class="ace-line list-div" data-node="true" dir="auto"><ul class="list-bullet1 r-list r-list-bullet"><li><span data-string="true" data-leaf="true">情节发展走向：主角凭借特殊能力崭露头角，引发各方关注，与关键角色（对手、导师）产生交集，同时特殊能力或法宝暴露，引发潜在危机。</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ul></div><div class="ace-line ol-idKy29ujSN list-div" data-node="true" dir="auto"><ol class="list-number1 r-list r-list-number" data-origin-start="3" start="3" data-start="3"><li style="font-weight:bold;" start="3" data-start="3"><span data-string="true" style="font-weight:bold;" data-leaf="true">空桑历练，情定碧瑶</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ol></div><div class="ace-line list-div" data-node="true" dir="auto"><ul class="list-bullet1 r-list r-list-bullet"><li><span data-string="true" data-leaf="true">通用前提：主角接受组织任务（历练、探险），进入特殊危险区域（秘境、敌境），在此过程中与敌对势力角色相遇，因共同目标或困境产生情感联结。</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ul></div><div class="ace-line list-div" data-node="true" dir="auto"><ul class="list-bullet1 r-list r-list-bullet"><li><span data-string="true" data-leaf="true">情节发展走向：主角与敌对角色从对抗到合作，逐渐突破阵营隔阂产生感情，任务结束后因身份差异被迫分离，感情成为后续情节冲突点。</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ul></div><div class="ace-line ol-idBg2xRptX list-div" data-node="true" dir="auto"><ol class="list-number1 r-list r-list-number" data-origin-start="4" start="4" data-start="4"><li style="font-weight:bold;" start="4" data-start="4"><span data-string="true" style="font-weight:bold;" data-leaf="true">真相暴露，叛出青云</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ol></div><div class="ace-line list-div" data-node="true" dir="auto"><ul class="list-bullet1 r-list r-list-bullet"><li><span data-string="true" data-leaf="true">通用前提：主角隐藏的秘密（身份、功法）被发现，面临组织内部的审判与质疑，同时得知与自身命运紧密相关的重大真相（身世、阴谋）。</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ul></div><div class="ace-line list-div" data-node="true" dir="auto"><ul class="list-bullet1 r-list r-list-bullet"><li><span data-string="true" data-leaf="true">情节发展走向：主角为坚守信念或保护重要之人，与原组织决裂，被迫转换身份（加入敌对势力、成为通缉犯），开启复仇或追寻真相之路。</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ul></div><div class="ace-line ol-idxilE50g3 list-div" data-node="true" dir="auto"><ol class="list-number1 r-list r-list-number" data-origin-start="5" start="5" data-start="5"><li style="font-weight:bold;" start="5" data-start="5"><span data-string="true" style="font-weight:bold;" data-leaf="true">十年寻觅，情牵雪琪</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ol></div><div class="ace-line list-div" data-node="true" dir="auto"><ul class="list-bullet1 r-list r-list-bullet"><li><span data-string="true" data-leaf="true">通用前提：主角转换身份后，在新阵营（魔教、反派组织）中因理念冲突产生自我挣扎，同时为实现重要目标（复活爱人、复仇）不断探索。</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ul></div><div class="ace-line list-div" data-node="true" dir="auto"><ul class="list-bullet1 r-list r-list-bullet"><li><span data-string="true" data-leaf="true">情节发展走向：主角在执行目标过程中，与旧爱重逢产生情感纠葛，结识新伙伴获取关键线索，目标因意外因素（人物死亡、线索中断）遭遇重大挫折。</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ul></div><div class="ace-line ol-iduTpCqtZz list-div" data-node="true" dir="auto"><ol class="list-number1 r-list r-list-number" data-origin-start="6" start="6" data-start="6"><li style="font-weight:bold;" start="6" data-start="6"><span data-string="true" style="font-weight:bold;" data-leaf="true">兽妖入侵，携手抗敌</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ol></div><div class="ace-line list-div" data-node="true" dir="auto"><ul class="list-bullet1 r-list r-list-bullet"><li><span data-string="true" data-leaf="true">通用前提：天下出现超越正邪对立的巨大危机（外敌入侵、灾难降临），迫使原本对立的阵营（正魔两道）暂时联合，主角因特殊能力成为关键人物。</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ul></div><div class="ace-line list-div" data-node="true" dir="auto"><ul class="list-bullet1 r-list r-list-bullet"><li><span data-string="true" data-leaf="true">情节发展走向：主角在联合行动中发挥核心作用，推动各方合作，危机暂时解除后，阵营矛盾再次激化，主角陷入新的矛盾漩涡。</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ul></div><div class="ace-line ol-idxzP06OWa list-div" data-node="true" dir="auto"><ol class="list-number1 r-list r-list-number" data-origin-start="7" start="7" data-start="7"><li style="font-weight:bold;" start="7" data-start="7"><span data-string="true" style="font-weight:bold;" data-leaf="true">道玄入魔，真相浮现</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ol></div><div class="ace-line list-div" data-node="true" dir="auto"><ul class="list-bullet1 r-list r-list-bullet"><li><span data-string="true" data-leaf="true">通用前提：组织内部高层（领导者、权威人物）因力量失控（走火入魔、被蛊惑）引发混乱，主角作为知情者或关键人物被卷入纷争。</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ul></div><div class="ace-line list-div" data-node="true" dir="auto"><ul class="list-bullet1 r-list r-list-bullet"><li><span data-string="true" data-leaf="true">情节发展走向：主角与伙伴为阻止混乱扩大展开行动，在冲突中发现更多秘密，同时面临重要人物牺牲，推动主角进一步成长。</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ul></div><div class="ace-line ol-idrwoNLs22 list-div" data-node="true" dir="auto"><ol class="list-number1 r-list r-list-number" data-origin-start="8" start="8" data-start="8"><li style="font-weight:bold;" start="8" data-start="8"><span data-string="true" style="font-weight:bold;" data-leaf="true">四灵血阵，决战鬼王</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ol></div><div class="ace-line list-div" data-node="true" dir="auto"><ul class="list-bullet1 r-list r-list-bullet"><li><span data-string="true" data-leaf="true">通用前提：敌对势力首领（反派 BOSS）为实现极端目标（毁灭、统治）制造终极威胁（强大阵法、武器），主角因与反派的恩怨成为最终对抗者。</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ul></div><div class="ace-line list-div" data-node="true" dir="auto"><ul class="list-bullet1 r-list r-list-bullet"><li><span data-string="true" data-leaf="true">情节发展走向：主角联合各方力量，突破重重阻碍，在关键时刻爆发潜力，击败反派，拯救世界，完成自我救赎。</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ul></div><div class="ace-line ol-idXYtA0eLE list-div" data-node="true" dir="auto"><ol class="list-number1 r-list r-list-number" data-origin-start="9" start="9" data-start="9"><li style="font-weight:bold;" start="9" data-start="9"><span data-string="true" style="font-weight:bold;" data-leaf="true">隐居草庙，情归何处</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ol></div><div class="ace-line list-div" data-node="true" dir="auto"><ul class="list-bullet1 r-list r-list-bullet"><li><span data-string="true" data-leaf="true">通用前提：重大危机彻底解决，主角经历人生起伏后，对名利、恩怨失去追求，渴望回归平静生活。</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ul></div><div class="ace-line list-div" data-node="true" dir="auto"><ul class="list-bullet1 r-list r-list-bullet"><li><span data-string="true" data-leaf="true">情节发展走向：主角放弃世俗身份，回归初心之地，与重要之人重逢，故事在开放式结局中引发对人生意义的思考。</span><span data-string="true" data-enter="true" data-leaf="true">​</span></li></ul></div></div></div></div>
"""
    result = doubao_parse_html_to_string(aaa)
    print(result)
