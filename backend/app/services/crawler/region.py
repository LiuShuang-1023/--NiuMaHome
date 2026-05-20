"""城市/区域 → 链家拼音映射

第一版手动维护，后续可改为查询数据库。
"""

# 区域名 → 链家 URL 拼音
DISTRICT_PINYIN = {
    # 广州
    "番禺": "panyu", "番禺区": "panyu",
    "天河": "tianhe", "天河区": "tianhe",
    "海珠": "haizhu", "海珠区": "haizhu",
    "越秀": "yuexiu", "越秀区": "yuexiu",
    "白云": "baiyun", "白云区": "baiyun",
    "黄埔": "huangpu", "黄埔区": "huangpu",
    "荔湾": "liwan", "荔湾区": "liwan",
    "南沙": "nansha", "南沙区": "nansha",
    "花都": "huadu", "花都区": "huadu",
    "增城": "zengcheng", "增城区": "zengcheng",
    "从化": "conghua", "从化区": "conghua",

    # 深圳
    "南山": "nanshan", "南山区": "nanshan",
    "福田": "futian", "福田区": "futian",
    "罗湖": "luohu", "罗湖区": "luohu",
    "宝安": "baoan", "宝安区": "baoan",
    "龙岗": "longgang", "龙岗区": "longgang",
    "龙华": "longhua", "龙华区": "longhua",

    # 北京
    "海淀": "haidian", "海淀区": "haidian",
    "朝阳": "chaoyang", "朝阳区": "chaoyang",
    "西城": "xicheng", "西城区": "xicheng",
    "东城": "dongcheng", "东城区": "dongcheng",
    "丰台": "fengtai", "丰台区": "fengtai",
    "昌平": "changping", "昌平区": "changping",

    # 上海
    "浦东": "pudong", "浦东新区": "pudong",
    "徐汇": "xuhui", "徐汇区": "xuhui",
    "静安": "jingan", "静安区": "jingan",
    "黄浦": "huangpu", "黄浦区": "huangpu",
    "长宁": "changning", "长宁区": "changning",
    "闵行": "minhang", "闵行区": "minhang",
    "杨浦": "yangpu", "杨浦区": "yangpu",
    "普陀": "putuo", "普陀区": "putuo",
}


def to_pinyin(district: str) -> str:
    """区域名 → 拼音"""
    return DISTRICT_PINYIN.get(district.strip(), "")
