from __future__ import annotations

import html
import zipfile
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "diet-delushan_PRD与技术方案.docx"


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def r(text: str, *, bold: bool = False, color: str | None = None, size: int | None = None) -> str:
    props = []
    if bold:
        props.append("<w:b/>")
    if color:
        props.append(f'<w:color w:val="{color}"/>')
    if size:
        props.append(f'<w:sz w:val="{size * 2}"/>')
    rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{esc(text)}</w:t></w:r>'


def p(
    text: str = "",
    *,
    style: str | None = None,
    bold: bool = False,
    color: str | None = None,
    size: int | None = None,
    spacing_after: int | None = None,
    num_id: int | None = None,
    level: int = 0,
) -> str:
    ppr = []
    if style:
        ppr.append(f'<w:pStyle w:val="{style}"/>')
    if spacing_after is not None:
        ppr.append(f'<w:spacing w:after="{spacing_after}"/>')
    if num_id is not None:
        ppr.append(f'<w:numPr><w:ilvl w:val="{level}"/><w:numId w:val="{num_id}"/></w:numPr>')
    ppr_xml = f"<w:pPr>{''.join(ppr)}</w:pPr>" if ppr else ""
    return f"<w:p>{ppr_xml}{r(text, bold=bold, color=color, size=size)}</w:p>"


def heading(text: str, level: int) -> str:
    return p(text, style=f"Heading{level}")


def bullet(text: str) -> str:
    return p(text, num_id=1)


def table(rows: list[list[str]], widths: list[int] | None = None) -> str:
    if not rows:
        return ""
    col_count = len(rows[0])
    if widths is None:
        base = 9360 // col_count
        widths = [base] * col_count
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    trs = []
    for row_index, row in enumerate(rows):
        cells = []
        for cell_index, cell in enumerate(row):
            fill = '<w:shd w:val="clear" w:color="auto" w:fill="F2F4F7"/>' if row_index == 0 else ""
            bold_run = row_index == 0
            cell_paras = "".join(p(part.strip(), bold=bold_run, spacing_after=0) for part in cell.split("\n") if part.strip())
            if not cell_paras:
                cell_paras = p("", spacing_after=0)
            cells.append(
                f'<w:tc><w:tcPr><w:tcW w:w="{widths[cell_index]}" w:type="dxa"/>{fill}'
                '<w:tcMar><w:top w:w="80" w:type="dxa"/><w:left w:w="120" w:type="dxa"/>'
                '<w:bottom w:w="80" w:type="dxa"/><w:right w:w="120" w:type="dxa"/></w:tcMar>'
                '<w:vAlign w:val="center"/></w:tcPr>'
                f"{cell_paras}</w:tc>"
            )
        trs.append(f"<w:tr>{''.join(cells)}</w:tr>")
    return (
        '<w:tbl><w:tblPr><w:tblW w:w="9360" w:type="dxa"/><w:tblInd w:w="120" w:type="dxa"/>'
        '<w:tblBorders><w:top w:val="single" w:sz="4" w:color="D9E2EC"/>'
        '<w:left w:val="single" w:sz="4" w:color="D9E2EC"/><w:bottom w:val="single" w:sz="4" w:color="D9E2EC"/>'
        '<w:right w:val="single" w:sz="4" w:color="D9E2EC"/><w:insideH w:val="single" w:sz="4" w:color="D9E2EC"/>'
        '<w:insideV w:val="single" w:sz="4" w:color="D9E2EC"/></w:tblBorders><w:tblLayout w:type="fixed"/></w:tblPr>'
        f"<w:tblGrid>{grid}</w:tblGrid>{''.join(trs)}</w:tbl>"
    )


def callout(title: str, body: str) -> str:
    return (
        '<w:tbl><w:tblPr><w:tblW w:w="9360" w:type="dxa"/><w:tblInd w:w="120" w:type="dxa"/>'
        '<w:tblBorders><w:top w:val="single" w:sz="4" w:color="E2E8F0"/><w:left w:val="single" w:sz="4" w:color="E2E8F0"/>'
        '<w:bottom w:val="single" w:sz="4" w:color="E2E8F0"/><w:right w:val="single" w:sz="4" w:color="E2E8F0"/>'
        '</w:tblBorders><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid><w:gridCol w:w="9360"/></w:tblGrid><w:tr><w:tc>'
        '<w:tcPr><w:tcW w:w="9360" w:type="dxa"/><w:shd w:val="clear" w:color="auto" w:fill="F4F6F9"/>'
        '<w:tcMar><w:top w:w="140" w:type="dxa"/><w:left w:w="180" w:type="dxa"/><w:bottom w:w="140" w:type="dxa"/>'
        '<w:right w:w="180" w:type="dxa"/></w:tcMar></w:tcPr>'
        f'{p(title, bold=True, color="1F3A5F", spacing_after=60)}{p(body, spacing_after=0)}</w:tc></w:tr></w:tbl>'
    )


def styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="120" w:line="264" w:lineRule="auto"/></w:pPr><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Microsoft YaHei"/><w:sz w:val="22"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="160"/></w:pPr><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Microsoft YaHei"/><w:b/><w:color w:val="0B2545"/><w:sz w:val="44"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="160"/></w:pPr><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Microsoft YaHei"/><w:color w:val="555555"/><w:sz w:val="24"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="320" w:after="160"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Microsoft YaHei"/><w:b/><w:color w:val="2E74B5"/><w:sz w:val="32"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Microsoft YaHei"/><w:b/><w:color w:val="2E74B5"/><w:sz w:val="26"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="160" w:after="80"/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Microsoft YaHei"/><w:b/><w:color w:val="1F4D78"/><w:sz w:val="24"/></w:rPr></w:style>
</w:styles>"""


def numbering_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum>
  <w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num>
</w:numbering>"""


def add_section(blocks: list[str], title: str, paragraphs: list[str]) -> None:
    blocks.append(heading(title, 1))
    for paragraph in paragraphs:
        blocks.append(p(paragraph))


def content_blocks() -> list[str]:
    blocks: list[str] = []
    blocks.append(p("Diet Delushan 单位食堂 AI 健康供餐智能体平台 PRD 与技术方案", style="Title"))
    blocks.append(p("面向企业、学校、园区、医院及机关单位食堂的 B 端健康菜单规划与智能供餐辅助系统", style="Subtitle"))
    blocks.append(table([
        ["项目", "内容"],
        ["产品定位", "单位食堂 B 端 AI 健康供餐智能体平台"],
        ["目标客户", "企业食堂、学校食堂、园区食堂、医院职工食堂、机关事业单位食堂、团餐服务商"],
        ["核心能力", "体检报告 Markdown 解析、团体健康画像、食堂菜品数据库筛选、周/月菜单规划、忌口与禁忌菜品建议、餐食图片分析、供餐运营辅助"],
        ["文档版本", "V2.0 B 端修订版"],
        ["生成日期", date.today().isoformat()],
    ], widths=[2200, 7160]))
    blocks.append(callout(
        "核心结论",
        "Diet Delushan 不是面向个人消费者的 C 端饮食助手，而是面向单位食堂和团餐运营方的 B 端智能体系统。系统的主要目标不是让单个用户随便问食谱，而是帮助单位食堂在已有人群健康信息、菜品数据库、季节地区约束、供餐成本与食堂执行能力的基础上，生成更适合职工、学生或机构成员的健康菜单，并为食堂管理者、营养管理人员和用餐人群提供可解释的 AI 辅助决策。"
    ))

    sections = [
        ("一、项目背景与业务问题", [
            "单位食堂承担的是群体供餐任务，不同于个人在家做饭或外卖点餐。企业、学校、园区、医院和机关单位食堂每天要面对固定或半固定人群，既要保证菜品供应稳定、成本可控、制作可执行，又要回应越来越明显的健康饮食诉求。现实中，很多单位已经组织年度体检，也积累了员工或成员的健康趋势，但这些数据往往停留在体检报告系统或纸质报告中，没有真正转化成食堂菜单设计和供餐策略。",
            "传统食堂菜单制定通常依赖厨师经验、采购习惯和固定轮换表。这样的方式能保证基本供应，但很难系统性考虑高血压、控糖、血脂异常、尿酸偏高、脂肪肝、肥胖、胃肠不适等常见健康问题。食堂即使想做健康供餐，也会遇到几个困难：体检报告难以理解，健康需求难以聚合，菜品与营养关系难以维护，菜单日期和季节适配容易出错，个体忌口咨询无法规模化响应。",
            "Diet Delushan 的 B 端价值在于把体检报告、食堂菜品库、菜单规划和多智能体问答连接起来。系统用体检报告解析 agent 把报告转换为 Markdown 健康信息，再把这份信息作为后续 agent 的共享上下文；食谱规划 agent 不再完全依赖大模型凭空生成菜谱，而是先让大模型提取筛选条件，再从单位食堂菜品数据库中取候选菜品，最后由大模型完成菜单组合、解释和展示。"
        ]),
        ("二、产品定位", [
            "本项目定位为“单位食堂 AI 健康供餐智能体平台”。它服务的首要对象是组织和食堂运营方，而不是单个消费者。系统可以用于单位内部健康食堂建设、团餐服务商菜单优化、园区食堂数字化升级、企业员工健康管理配套和学校或医院职工餐饮场景。",
            "产品形态可以理解为一个面向食堂管理和健康供餐的智能工作台：后端多智能体负责解析报告、识别意图、生成画像、回答忌口问题、规划食谱、分析餐食图片和复盘饮食记录；前端以聊天交互承载 AI 结果，同时保留体检报告上传、菜品图片上传、对话历史和食谱输出等入口。",
            "系统边界必须清楚：Diet Delushan 不做医疗诊断，不替代医生和临床营养师，不输出治疗方案，不做风险等级判定。它做的是食堂供餐辅助、健康饮食建议和菜单规划。所有涉及疾病、异常指标和复查的问题，都应把结论落到饮食选择、菜品替代、份量控制、烹饪方式和就医咨询提醒上。"
        ]),
        ("三、目标客户与用户角色", [
            "目标客户一是企业与园区食堂。企业员工长期在单位食堂就餐，食堂菜单对员工健康影响很大。企业可以把年度体检后的共性问题转化为供餐优化方向，例如减少高油高盐菜品频次、增加优质蛋白和蔬菜比例、设计控糖友好窗口、优化夜班或加班餐。",
            "目标客户二是学校与教育机构食堂。学校食堂需要考虑学生成长、教师职工健康、食品安全和营养均衡。系统可辅助食堂制定一周或一月菜单，说明早餐、午餐、晚餐搭配逻辑，并根据季节和地区调整菜品。",
            "目标客户三是医院、机关和事业单位食堂。这类场景对健康饮食、慢病友好餐、低盐低脂供餐和营养说明要求更高。系统可以辅助营养管理人员快速生成菜单草案、忌口说明和菜品替换建议。",
            "目标客户四是团餐服务商。团餐服务商服务多个单位，需要在不同地区、不同季节、不同预算和不同人群特征下快速生成菜单方案。Diet Delushan 可以把菜单生成从经验驱动改成“规则 + 数据库 + 大模型解释”的组合模式。",
            "主要用户角色包括食堂管理员、厨师长、采购人员、营养师或健康管理人员、单位后勤管理人员，以及最终查看建议的职工或学生。B 端系统应优先满足管理员和运营方的配置、生成、审核和落地需求，面向普通用餐者的聊天回答是辅助入口，不是唯一产品形态。"
        ]),
        ("四、业务目标", [
            "业务目标一是提升单位食堂菜单规划效率。系统应支持管理员输入“规划下周食谱”“生成夏季江浙地区职工食堂菜单”“为控糖和高血压人群设计一周菜单”等需求，快速得到可执行的 Markdown 菜单结果。",
            "业务目标二是提高健康供餐的解释能力。食堂不只是给出菜名，还要说明为什么这样搭配、哪些菜适合哪些人群、哪些菜应少吃或避免、食材归类和营养估算依据是什么。系统应让菜单从“经验安排”变成“可解释安排”。",
            "业务目标三是减少大模型幻觉。食谱规划 agent 应优先基于单位已有菜品数据库生成候选，而不是让大模型凭空编菜。数据库中的 season、region、suitable_people、avoid_people、ingredients 等字段应参与筛选和解释。",
            "业务目标四是支持健康管理闭环。体检报告上传后，系统形成 Markdown 健康上下文；用户或管理员后续询问忌口、食谱、菜品选择、餐食图片和历史饮食复盘时，最终执行 agent 统一读取这份上下文。"
        ]),
        ("五、核心功能范围", [
            "体检报告解析功能负责接收 PDF、txt、md 或 json 等报告内容，把报告整理为可读 Markdown。该 Markdown 既是前端展示正文，也是后续所有 agent 的共享健康上下文。当前项目不再维护复杂 MedicalReportData 结构，也不再把报告强制拆成大量 JSON 字段。",
            "用户画像功能在 B 端语境下应理解为“健康背景说明”或“群体/个体健康摘要”。当需要生成画像时，系统把体检报告 Markdown 和当前问题交给大模型，返回一份可读 Markdown，供食堂管理员或用户理解健康关注点。它不应重复构造复杂 JSON，也不应在不必要时重复调用画像生成。",
            "忌口建议功能用于回答“这类人不能吃什么”“高尿酸少吃哪些菜”“控糖人群食堂点餐应该避免什么”“这几道菜哪个更适合”等问题。HealthRiskAgent 在本项目中不做风险等级评估，而是作为忌口和禁忌菜品建议 agent，读取报告 Markdown 与用户问题后调用大模型返回 Markdown。",
            "食谱规划功能是 B 端核心能力。系统先让大模型基于报告 Markdown、当前日期、单位场景和用户问题生成数据库筛选条件，例如 season、region、people_type、avoid_people；其中 season 必须包含“四季”，如能判断季节再加入“夏、冬”等；region 必须包含“通用”，如能判断地区再加入“江浙、川渝”等。",
            "菜品数据库功能用于承载真实食堂可做菜品。当前规划包含汤类、主食类、素菜类、荤菜类、水产类、早餐类六类表。每道菜应尽量维护 name、ingredients、season、region、suitable_meal、suitable_people、avoid_people、is_canteen_suitable 等字段。食谱生成时应从数据库取候选菜，再组合早餐、午餐、晚餐和加餐。",
            "餐食图片分析功能用于识别单张食物图片或餐前餐后两张图片。单张图片用于分析当前餐食种类、估算克数、热量和营养结构；两张图片用于计算实际吃掉的食物，并可保存为饮食记录。B 端场景下，该能力可用于抽样评估食堂实际摄入情况。"
        ]),
    ]
    for title, paragraphs in sections:
        add_section(blocks, title, paragraphs)

    blocks.append(heading("六、B 端核心用户流程", 1))
    for item in [
        "单位食堂管理员或健康管理人员进入系统，创建当前单位或当前会话上下文。",
        "管理员上传员工体检报告、样例报告或群体健康摘要，Report Parser Agent 调用大模型生成 Markdown 健康上下文。",
        "系统把 Markdown 写入 WorkflowState，并作为后续所有 agent 可读取的共享报告正文。",
        "管理员提出菜单需求，例如“规划下周职工食堂食谱”“为高血压和控糖人群生成夏季菜单”“今天这几道菜哪些要少吃”。",
        "Master Agent 负责意图路由，但不把路由思考展示给前端；最终执行 agent 才流式输出大模型思考过程和最终答案。",
        "Recipe Generation Agent 先生成筛选条件，再查询六类菜品数据库，再构建候选餐次组合，最后让大模型输出 Markdown 菜单。",
        "HealthRiskAgent 在忌口或禁忌菜品问题中读取报告 Markdown 与用户问题，生成可执行的少吃、避免、可替代菜品建议。",
        "管理员可把生成结果用于菜单草案、食堂窗口说明、健康餐推荐、内部展示或后续人工审核。"
    ]:
        blocks.append(bullet(item))

    blocks.append(heading("七、食谱规划 Agent 详细设计", 1))
    for paragraph in [
        "食谱规划 agent 是当前项目最需要体现 B 端价值的模块。它不应只像 C 端助手一样输出“明天吃什么”，而应围绕单位食堂真实供餐进行菜单组合。输入包括用户问题、当前日期、星期信息、体检报告 Markdown、可选的单位类型或地区信息、菜品数据库候选数据。",
        "第一步是大模型提取数据库筛选条件。模型返回 JSON 条件不是为了给用户展示，而是为了系统查询数据库。条件中 season 必须包含“四季”，region 必须包含“通用”，avoid_people 应从报告和问题中提取控糖、高血压、高尿酸、低脂、低盐等标签。该 JSON 属于系统可计算中间结果，不是最终用户答案。",
        "第二步是数据库查询。系统分别查询汤类、主食类、素菜类、荤菜类、水产类、早餐类。查询时应按 season、region、suitable_people、avoid_people 等字段过滤，避免把明显不适合的人群禁忌菜品作为候选。",
        "第三步是候选餐次组合。早餐从早餐类选择 1 到 2 个；午餐由主食 1 个、汤 1 个、荤菜或水产 1 个、素菜 1 个组成；晚餐结构同午餐；晚间加餐从主食或早餐类选择 1 个。系统应尽量保证每天菜品不同，相邻两天菜品尽量不重复。",
        "第四步是大模型生成最终 Markdown。此时模型不是凭空想菜，而是在候选餐次基础上做分配、解释、份量估算和营养说明。输出应包含日期、星期、餐次、菜品、食材归类、推荐理由、禁忌提醒和替换方案。"
    ]:
        blocks.append(p(paragraph))

    blocks.append(heading("八、菜品数据库与字段设计", 1))
    blocks.append(table([
        ["分类", "表名建议", "用途"],
        ["汤类", "soup_porridge", "午餐和晚餐搭配，控制油盐，补充水分与部分蛋白或蔬菜"],
        ["主食类", "staple_food", "早餐、午餐、晚餐和加餐的碳水来源"],
        ["素菜类", "vegetable_dish", "提供蔬菜、膳食纤维、低能量菜品组合"],
        ["荤菜类", "meat_dish", "提供肉蛋禽等蛋白来源"],
        ["水产类", "aquatic_dish", "归入荤菜/优质蛋白组合，适合替代部分高脂肉类"],
        ["早餐类", "breakfast_snack", "早餐 1 到 2 个菜品，也可作为晚间加餐候选"],
    ], widths=[1600, 2400, 5360]))
    for item in [
        "name：菜品名称，用于菜单展示。",
        "ingredients：菜品食材字段，用于食物元素归类，不能让大模型把菜名直接复制成食材归类。",
        "season：季节标签，必须支持“四季”，也可包含“春、夏、秋、冬”。",
        "region：地区标签，必须支持“通用”，也可包含“江浙、川渝、华北、华南”等。",
        "suitable_meal：适合餐次，例如早餐、午餐、晚餐、加餐。",
        "suitable_people：适合人群，例如普通职工、控糖、低脂、高蛋白、学生等。",
        "avoid_people：不适合或需谨慎人群，例如高尿酸、高血压、控糖、肾功能异常等。",
        "is_canteen_suitable：是否适合食堂批量制作。"
    ]:
        blocks.append(bullet(item))

    blocks.append(heading("九、食物元素归类规则", 1))
    for paragraph in [
        "食物元素归类不是菜品归类，而是食材归类。过去让大模型自己做归类时，模型容易把“红烧鱼、青椒肉丝、紫菜蛋花汤”这类菜名复制到元素归类中，导致结果不符合营养解释需求。",
        "新的规则是：数据库每道菜必须维护 ingredients 字段，系统在查询菜品后先解析 ingredients，并按主食/碳水、优质蛋白、蔬菜、水果、奶豆类、油脂坚果等类别做初步归类。大模型只负责根据这些食材重新估算克数、解释营养结构和给出搭配建议，不再自行把菜名当作食材。",
        "例如“青椒肉丝”的 ingredients 为“猪肉丝、青椒、木耳”，系统可归类为优质蛋白：猪肉丝；蔬菜：青椒、木耳。最终菜单可以展示菜品名称，但在食物元素归类中必须展示食材，而不是重复菜品名称。"
    ]:
        blocks.append(p(paragraph))

    blocks.append(heading("十、多智能体职责划分", 1))
    blocks.append(table([
        ["Agent", "B 端职责", "输出格式"],
        ["Master Agent", "识别用户意图并路由到最终执行 agent，不展示路由思考", "内部路由结果"],
        ["Report Parser Agent", "解析单位成员体检报告或健康摘要，生成共享健康上下文", "Markdown"],
        ["User Profile Agent", "按需生成健康背景说明，辅助管理员理解报告关注点", "Markdown"],
        ["HealthRiskAgent", "回答忌口、禁忌菜品、少吃什么、食堂点餐避开什么", "Markdown"],
        ["Recipe Generation Agent", "结合报告 Markdown 与菜品数据库生成单位食堂菜单", "Markdown"],
        ["Nutrition Analysis Agent", "分析餐食图片或饮食内容的营养结构", "Markdown"],
        ["Recommendation Agent", "给出供餐优化、替换菜品和运营建议", "Markdown"],
    ], widths=[2200, 4960, 2200]))
    for paragraph in [
        "B 端项目中，agent 的职责应围绕食堂业务流转，而不是围绕个人聊天体验堆功能。Report Parser Agent 负责把健康信息变成共享上下文；Recipe Generation Agent 负责把健康需求转成真实菜单；HealthRiskAgent 负责把健康限制转成可执行忌口建议；图片分析 agent 用于餐食识别和记录。",
        "所有面向用户或管理员展示的最终答案优先使用 Markdown。只有系统内部确实需要计算时，例如食谱数据库筛选条件，才使用 JSON。这样既保留了业务可读性，又避免把前端展示强行绑到复杂结构字段。"
    ]:
        blocks.append(p(paragraph))

    blocks.append(heading("十一、前端产品形态", 1))
    for paragraph in [
        "前端当前以聊天界面承载智能体结果，但 B 端产品不应只停留在聊天机器人。后续可扩展为食堂管理工作台，包括报告上传区、菜单生成区、菜品数据库管理区、健康供餐说明区、历史菜单区和餐食图片分析区。",
        "移动端应以消息阅读和问题输入为主，隐藏复杂项目能力介绍、对话历史、左侧菜单和重复标题，输入框固定在底部。B 端管理员可能在食堂现场或会议中临时查看菜单建议，因此移动端要保证快速提问、快速阅读、快速上传图片。",
        "前端展示给普通用餐者的菜单不应出现内部 agent 名称，例如 Report Parser Agent、Health Risk Agent。可以合并为“健康报告与忌口建议”之类的用户可理解入口。后端 agent 职责可以保持不变，前端菜单命名应面向业务用户。"
    ]:
        blocks.append(p(paragraph))

    blocks.append(heading("十二、流式输出与大模型思考过程", 1))
    for paragraph in [
        "系统只需要展示最终执行任务 agent 的大模型实时思考过程和最终答案，不需要展示意图识别或路由阶段的思考过程。路由思考对 B 端用户没有业务价值，反而会干扰管理员理解菜单生成或忌口建议。",
        "实时思考过程应来自实际调用大模型的流式接口，而不是后端手写的系统进度。后端可以保留必要的进度事件用于调试，但前端展示时应区分“模型思考”和“系统状态”。",
        "提示词可加入“思考过程尽量使用中文，并且推理功能是面向大众普通用户，尽量不要使用英文推理”。但该约束不能保证 reasoning_content 100% 中文，因为推理 token 受模型供应商策略、预训练语料和模型自身推理习惯影响。产品验收应以尽量中文、可读、不影响理解为目标。"
    ]:
        blocks.append(p(paragraph))

    blocks.append(heading("十三、技术架构", 1))
    for paragraph in [
        "后端采用 FastAPI 服务承载聊天、文件上传、SSE 流式输出和智能体工作流。核心状态由 WorkflowState 维护，其中 medical_report 字段保存体检报告 Markdown，latest_profile_reply 等字段保存最新可展示结果。服务层 llm_service 负责统一调用大模型，包括普通补全、带 thinking 的流式补全、图片分析和食谱规划。",
        "数据库层使用 MySQL 和 SQLAlchemy。食谱数据库是 B 端菜单生成的关键资产，后续应从演示 SQL 扩展到正式菜品管理后台。每个单位或食堂可以有自己的菜品库、地区标签、季节标签和禁忌规则，因此生产环境必须引入 tenant_id 或 canteen_id 做数据隔离。",
        "前端采用 Vite/React 形态，负责聊天消息、文件上传、菜单展示、移动端适配和 SSE 事件渲染。前端不应理解复杂医疗结构字段，而应渲染后端返回的 Markdown、thinking 流和必要状态。"
    ]:
        blocks.append(p(paragraph))

    blocks.append(heading("十四、数据流设计", 1))
    for item in [
        "报告上传数据流：文件上传 -> 文件类型识别 -> Report Parser Agent -> 大模型解析 -> Markdown 报告 -> WorkflowState 与缓存共享。",
        "忌口问答数据流：用户问题 -> 意图路由 -> HealthRiskAgent -> 报告 Markdown + 用户问题 -> 大模型 -> Markdown 忌口建议。",
        "食谱生成数据流：用户问题 -> Recipe Generation Agent -> 大模型提取筛选条件 -> 查询六类菜品库 -> 构造候选餐次 -> 大模型生成 Markdown 食谱。",
        "图片分析数据流：单张或两张图片上传 -> 视觉模型识别 -> 克数与营养估算 -> Markdown 分析或饮食记录。",
        "前端流式数据流：最终执行 agent 调用大模型 -> reasoning_content 作为思考过程流式输出 -> content 作为最终答案流式输出 -> done 事件结束。"
    ]:
        blocks.append(bullet(item))

    blocks.append(heading("十五、非功能需求", 1))
    for item in [
        "可用性：菜单生成即使数据库候选为空，也应返回可解释提示，说明需要检查数据库连接、SQL 是否执行和字段标签是否匹配。",
        "可维护性：提示词优先中文化，面向用户输出优先 Markdown，内部结构化 JSON 只用于必要的系统计算。",
        "稳定性：SSE 流式输出中断时，前端应保留已收到内容，后端应输出错误事件或重试提示。",
        "安全性：体检报告、健康信息和饮食记录属于敏感信息，生产环境必须按单位、用户或租户隔离。",
        "可扩展性：菜品数据库应支持不同单位独立维护，未来可增加成本、库存、窗口、厨师工艺、过敏原、营养成分表等字段。",
        "准确性：食谱日期必须由后端或提示词明确约束。用户说“下周”时，应从当前周的下一周周一开始，而不能复用今天日期。"
    ]:
        blocks.append(bullet(item))

    blocks.append(heading("十六、验收标准", 1))
    blocks.append(table([
        ["场景", "输入", "预期结果"],
        ["报告解析", "上传体检报告 PDF", "返回结构清晰的 Markdown 健康报告，并写入共享上下文"],
        ["忌口建议", "高尿酸员工食堂少吃什么", "HealthRiskAgent 调用大模型返回少吃、避免、替代菜品建议，不输出风险等级"],
        ["下周菜单", "今天 6 月 1 日，规划下周食谱", "第一天从 6 月 8 日开始，按正确日期和星期输出"],
        ["数据库筛选", "生成夏季江浙职工食堂菜单", "筛选条件 season 包含四季和夏，region 包含通用和江浙"],
        ["菜品候选", "数据库已写入六类菜品", "recipe_database_candidates 能返回汤、主食、素菜、荤菜、水产、早餐候选"],
        ["食材归类", "青椒肉丝", "食物元素归类展示猪肉丝、青椒、木耳等食材，不把青椒肉丝当作元素"],
        ["流式思考", "食谱生成问题", "只展示 Recipe Generation Agent 的大模型思考过程和最终答案"],
        ["移动端", "手机访问首页", "隐藏复杂菜单和项目能力，输入框固定底部，消息阅读优先"]
    ], widths=[1800, 3000, 4560]))

    blocks.append(heading("十七、风险与处理策略", 1))
    for item in [
        "数据库连接失败：优先检查 backend/.env 的 MYSQL_HOST、MYSQL_PORT、MYSQL_USER、MYSQL_PASSWORD、MYSQL_DB，修改后必须重启后端。",
        "菜品候选为空：检查 tempsql 或 new.sql 是否执行到当前数据库，六类表是否存在，season 是否包含四季，region 是否包含通用。",
        "大模型生成虚构菜品：提示词必须要求优先使用 candidate_meal_plan，数据库候选不足时明确说明，不应假装来自数据库。",
        "食材归类错误：系统应优先用 ingredients 字段做归类，大模型只做克数和营养解释，不负责从菜名猜食材。",
        "医疗越界：涉及疾病诊断、用药和治疗时，系统必须提示咨询医生或营养师，并把建议限定在饮食层面。",
        "B 端与 C 端定位混乱：文档、前端菜单和提示词都应使用单位食堂、管理员、职工/学生群体、团餐运营等表述，避免把产品写成个人减肥助手。"
    ]:
        blocks.append(bullet(item))

    blocks.append(heading("十八、未来扩展方向", 1))
    for item in [
        "食堂菜品管理后台：支持管理员维护菜品、食材、成本、季节、地区、禁忌人群和窗口信息。",
        "单位健康看板：按群体健康趋势生成低盐、低脂、控糖、控尿酸等供餐建议。",
        "菜单审核流：AI 生成菜单后交由营养师、厨师长或后勤负责人审核再发布。",
        "采购联动：根据一周菜单自动汇总食材需求，辅助采购计划。",
        "营养成分数据库接入：将食材克数与标准食物成分表结合，减少大模型营养估算误差。",
        "多租户隔离：支持不同单位、不同食堂、不同窗口独立菜品库和菜单策略。",
        "员工端轻量入口：在 B 端管理基础上，为职工提供查看今日推荐、忌口提醒和拍照分析的轻量入口。"
    ]:
        blocks.append(bullet(item))

    blocks.append(heading("十九、总结", 1))
    blocks.append(p(
        "Diet Delushan 的正确产品方向是单位食堂 B 端 AI 健康供餐智能体平台。它的价值不在于给个人用户生成泛泛的健康食谱，而在于把单位体检信息、真实食堂菜品库、季节地区约束、忌口规则和多智能体大模型能力结合起来，帮助食堂管理者更快生成可解释、可执行、可审核的健康菜单。"
    ))
    blocks.append(p(
        "当前阶段应继续保持实现逻辑简单清晰：报告解析 agent 生成 Markdown 健康上下文，后续 agent 共享这份 Markdown；食谱规划 agent 使用大模型提取数据库筛选条件，再基于真实菜品候选生成 Markdown 菜单；忌口 agent 只回答饮食禁忌和替代建议，不做风险等级。这样既符合 B 端食堂业务，也能降低系统冗余和维护成本。"
    ))
    return blocks


def document_xml() -> str:
    body = "".join(content_blocks())
    sect = (
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" '
        'w:bottom="1440" w:left="1440" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<w:body>{body}{sect}</w:body></w:document>"
    )


def write_docx() -> Path:
    files = {
        "[Content_Types].xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>""",
        "_rels/.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>""",
        "word/_rels/document.xml.rels": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
</Relationships>""",
        "word/document.xml": document_xml(),
        "word/styles.xml": styles_xml(),
        "word/numbering.xml": numbering_xml(),
        "docProps/core.xml": f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Diet Delushan 单位食堂 AI 健康供餐智能体平台 PRD 与技术方案</dc:title>
  <dc:creator>Codex</dc:creator>
  <cp:lastModifiedBy>Codex</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{date.today().isoformat()}T00:00:00Z</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{date.today().isoformat()}T00:00:00Z</dcterms:modified>
</cp:coreProperties>""",
        "docProps/app.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Codex OOXML Writer</Application>
</Properties>""",
    }
    output = OUTPUT
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, data in files.items():
                zf.writestr(name, data)
    except PermissionError:
        output = ROOT / "diet-delushan_PRD与技术方案_B端版.docx"
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, data in files.items():
                zf.writestr(name, data)
    print(output)
    return output


if __name__ == "__main__":
    write_docx()
