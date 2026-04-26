# tools/schedule_from_xls.py
import pandas as pd
import json
import re
import os
from pathlib import Path
from datetime import date, datetime, timedelta
from dotenv import load_dotenv

# 加载项目根目录的 .env（若存在）
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# 🔑 工具元数据（Agent 框架自动注册用）
TOOL_SCHEMA = {
    "name": "query_bupt_xls_schedule",
    "description": "从本地 Excel 课表文件中查询课程。支持按星期、节次、自然日期、周次或课程名筛选。返回 Markdown 表格。",
    "parameters": {
        "type": "object",
        "properties": {
            "weekday": {"type": "integer", "description": "星期几 (1-7, 1=周一)"},
            "period": {"type": "integer", "description": "第几节 (1-12)"},
            "week_num": {"type": "integer", "description": "当前教学周次 (1-20)，用于过滤单/双周"},
            "course_name": {"type": "string", "description": "课程名称关键字（模糊匹配）"},
            "query_date": {"type": "string", "description": "自然日期（例如 2026-03-11、今天、明天、后天）"}
        },
        "required": []
    }
}

# 🕒 北邮标准作息表（可根据实际校历调整）
TIME_TABLE = {
    1: ("08:00", "08:45"),2: ("08:50", "09:35"), 3: ("09:50", "10:35"),4: ("10:40", "11:25"),
    5: ("13:00", "13:45"), 6: ("13:50", "14:35"), 7: ("14:45", "15:30"),8: ("15:40", "16:25"),
    9: ("16:40", "17:25"), 10: ("17:30", "18:15"), 11: ("19:20", "20:05"), 12: ("20:10", "20:55")
}

# 🗃️ 内存缓存（避免重复读文件）
_schedule_cache = None

def check_schedule_requirements() -> bool:
    return True
def _parse_natural_date(raw: str) -> date:
    """解析自然日期字符串，支持今天/明天/后天与常见日期格式。"""
    if raw is None:
        raise ValueError("query_date 不能为空")

    text = str(raw).strip()
    if not text:
        raise ValueError("query_date 不能为空")

    today = date.today()
    special = {
        "今天": today,
        "明天": today + timedelta(days=1),
        "后天": today + timedelta(days=2),
    }
    if text in special:
        return special[text]

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%m-%d", "%m/%d"):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt in ("%m-%d", "%m/%d"):
                return date(today.year, parsed.month, parsed.day)
            return parsed.date()
        except ValueError:
            continue

    raise ValueError("query_date 格式不支持，请使用 YYYY-MM-DD 或 今天/明天/后天")


def _resolve_week_from_date(query_date: date) -> tuple[int, int]:
    """
    根据自然日期换算教学周次与星期。
    依赖环境变量 SEMESTER_WEEK1_MONDAY (YYYY-MM-DD)。
    """
    semester_start_raw = os.getenv("SEMESTER_WEEK1_MONDAY", "").strip()
    if not semester_start_raw:
        raise ValueError("缺少环境变量 SEMESTER_WEEK1_MONDAY（格式示例：2026-02-24）")

    try:
        semester_start = datetime.strptime(semester_start_raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("环境变量 SEMESTER_WEEK1_MONDAY 格式错误，请使用 YYYY-MM-DD") from exc

    delta_days = (query_date - semester_start).days
    if delta_days < 0:
        raise ValueError("query_date 早于学期第一周周一，请检查日期或环境变量配置")

    week_num = delta_days // 7 + 1
    weekday = query_date.weekday() + 1  # Monday=1 ... Sunday=7
    return week_num, weekday

def _extract_period_range(period_text: str) -> tuple[int, int] | None:
    """从 '[01-02]节' 或 '第1-2节' 中提取节次范围。"""
    text = str(period_text).strip()
    bracket_match = re.search(r"\[([0-9\-]+)\]\s*节", text)
    if bracket_match:
        nums = [int(n) for n in re.findall(r"\d+", bracket_match.group(1))]
        if nums:
            return nums[0], nums[-1]

    plain_match = re.search(r"第\s*(\d+)(?:\s*-\s*(\d+))?\s*节", text)
    if plain_match:
        start = int(plain_match.group(1))
        end = int(plain_match.group(2)) if plain_match.group(2) else start
        return start, end
    return None


def _normalize_week_text(week_text: str) -> str:
    """标准化周次表达，兼容 2[周] / 第2周 / 1-16周 等格式。"""
    text = str(week_text).strip()
    text = re.sub(r"\s+", "", text)
    text = text.replace("第", "").replace("[周]", "").replace("周", "")
    text = text.replace("[", "").replace("]", "")
    return text or "全周"


def _parse_cell(cell_text: str) -> list[dict]:
    """
    解析单元格中的课程记录，支持两种常见格式：
    1) 旧格式：课程/教师/地点/周次
    2) 新格式：课程/教师/周次/地点/节次（一个单元格可重复多组）
    """
    text = str(cell_text).replace("<br>", "\n").replace("\r", "")
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return []

    entries = []
    idx = 0
    while idx + 4 < len(lines):
        # 多记录格式：课程, 教师, 周次, 地点, 节次
        if ("周" in lines[idx + 2]) and ("节" in lines[idx + 4]):
            period_range = _extract_period_range(lines[idx + 4])
            entry = {
                "course": lines[idx],
                "teacher": lines[idx + 1],
                "location": lines[idx + 3],
                "weeks": _normalize_week_text(lines[idx + 2]),
                "period_start": period_range[0] if period_range else None,
                "period_end": period_range[1] if period_range else None,
            }
            entries.append(entry)
            idx += 5
            continue
        idx += 1

    if entries:
        return entries

    # 兜底兼容旧格式（单条记录）
    period_range = _extract_period_range(lines[4]) if len(lines) > 4 else None
    return [{
        "course": lines[0] if len(lines) > 0 else "",
        "teacher": lines[1] if len(lines) > 1 else "",
        "location": lines[2] if len(lines) > 2 else "",
        "weeks": _normalize_week_text(lines[3]) if len(lines) > 3 else "全周",
        "period_start": period_range[0] if period_range else None,
        "period_end": period_range[1] if period_range else None,
    }]

def _match_week(week_str: str, current: int) -> bool:
    """判断当前周次是否符合课程周次规则"""
    week_str = _normalize_week_text(week_str)
    if not current or week_str in ("全周", "1-20", ""): return True
    if "单" in week_str: return current % 2 == 1
    if "双" in week_str: return current % 2 == 0
    
    for part in re.split('[,，]', week_str):
        if "-" in part:
            nums = [int(n) for n in re.findall(r"\d+", part)]
            if len(nums) >= 2:
                s, e = nums[0], nums[1]
                if s <= current <= e:
                    return True
        else:
            try:
                if int(part) == current:
                    return True
            except: pass
    return False

def load_schedule(xls_path: str) -> list:
    """将 Excel 网格拍平为课程列表"""
    df = pd.read_excel(xls_path, header=None)
    courses = []
    
    # 假设结构：第0行=表头，第0列=节次，数据从 [1,1] 开始
    for col in range(1, 8):  # 周一~周日
        for row in range(1, len(df)):
            cell = df.iloc[row, col]
            if pd.isna(cell) or str(cell).strip() == '': continue
            
            header = str(df.iloc[row, 0])
            match = re.search(r'第(\d+)-?(\d*)节', header)
            row_p_start = int(match.group(1)) if match else row
            row_p_end = int(match.group(2)) if match and match.group(2) else row_p_start

            infos = _parse_cell(cell)
            for info in infos:
                p_start = info.get("period_start") or row_p_start
                p_end = info.get("period_end") or row_p_end

                t_start = TIME_TABLE.get(p_start, ("08:00", "09:35"))[0]
                t_end = TIME_TABLE.get(p_end, TIME_TABLE.get(p_start, ("08:00", "09:35")))[1]
                courses.append({
                    "weekday": col,
                    "period_start": p_start,
                    "period_end": p_end,
                    "time_start": t_start,
                    "time_end": t_end,
                    "course": info.get("course", ""),
                    "teacher": info.get("teacher", ""),
                    "location": info.get("location", ""),
                    "weeks": info.get("weeks", "全周"),
                })
    return courses

def get_schedule(weekday: int = None, period: int = None,
                            week_num: int = None, course_name: str = None,
                            query_date: str = None) -> tuple[str, list]:
    global _schedule_cache
    if _schedule_cache is None:
        xls_path = os.getenv("SCHEDULE_XLS_PATH", "schedule.xls")
        if not Path(xls_path).exists():
            return "⚠️ 未找到课表文件。请设置环境变量 SCHEDULE_XLS_PATH 或将文件放在同级目录。"
        _schedule_cache = load_schedule(xls_path)

    date_note = ""
    if query_date:
        try:
            parsed_date = _parse_natural_date(query_date)
            derived_week_num, derived_weekday = _resolve_week_from_date(parsed_date)
        except ValueError as err:
            return f"⚠️ 日期查询失败：{err}"
        # 仅在未显式传入 weekday/week_num 时，使用自然日期换算值
        weekday = weekday or derived_weekday
        week_num = week_num or derived_week_num
        date_note = (
            f"📌 日期 `{parsed_date.isoformat()}` -> 第 `{derived_week_num}` 周，"
            f"周{['一', '二', '三', '四', '五', '六', '日'][derived_weekday - 1]}\n\n"
        )

    results = _schedule_cache
    if weekday: results = [c for c in results if c["weekday"] == weekday]
    if period: results = [c for c in results if c["period_start"] <= period <= c["period_end"]]
    if week_num: results = [c for c in results if _match_week(c["weeks"], week_num)]
    if course_name: results = [c for c in results if course_name.lower() in c["course"].lower()]
    
    if not results:
        return "📭 未找到匹配课程。或许那天没课😊",[]

    # 返回 Agent 友好的 Markdown
    day_map = {1:'一', 2:'二', 3:'三', 4:'四', 5:'五', 6:'六', 7:'日'}
    md = f"### 📅 课表查询结果\n\n{date_note}| 星期 | 节次 | 时间 | 课程 | 教师 | 地点 | 周次 |\n|---|---|---|---|---|---|---|\n"
    for c in results:
        md += f"| 周{day_map[c['weekday']]} | {c['period_start']}-{c['period_end']} | {c['time_start']}-{c['time_end']} | {c['course']} | {c['teacher']} | {c['location']} | {c['weeks']}周 |\n"
    return md,results


from tools.registry import registry, tool_result, tool_error

def query_bupt_xls_schedule(weekday: int = None, period: int = None,
                            week_num: int = None, course_name: str = None,
                            query_date: str = None) -> dict:
    try:
        schedule_md,schedule_list = get_schedule(weekday, period, week_num, course_name, query_date)
        res_json = {
            "success": True,
            "data": schedule_list,
            "markdown": schedule_md,
            "count": len(schedule_list)
        }
        res = tool_result(res_json)
    except Exception as e:
        return tool_error(f"查询课表失败: {e}")
    return res


QUERY_BUPT_XLS_SCHEDULE_SCHEMA = {
    "name": "get_course_schedule",
    "description":"从本地excel课表查询课程，支持自然日期、周次、节次、课程名字筛选。当用户需要你安排日程的时候，使用这个工具查看用户课表，避免安排冲突，并留足时间给用户休息。",
    "parameters": {
        "type": "object",
        "properties":{
            "weekday": {"type": "integer", "description": "星期几 (1-7, 1=周一)"},
            "period": {"type": "integer", "description": "第几节 (1-12)"},
            "week_num": {"type": "integer", "description": "当前教学周次 (1-20)，用于过滤单/双周"},
            "course_name": {"type": "string", "description": "课程名称关键字（模糊匹配）"},
            "query_date": {"type": "string", "description": "自然日期（例如 2026-03-11、今天、明天、后天）"}
        },
        "required": []
    }
}

registry.register(
    name="get_course_schedule",
    toolset="schedule",
    schema=QUERY_BUPT_XLS_SCHEDULE_SCHEMA,
    handler=lambda args, **kw:query_bupt_xls_schedule(
        weekday=args.get("weekday"),
        period=args.get("period"),
        week_num=args.get("week_num"),
        course_name=args.get("course_name"),
        query_date=args.get("query_date")
    ),
    check_fn=check_schedule_requirements,
    requires_env=["SCHEDULE_XLS_PATH","SEMESTER_WEEK1_MONDAY"],
    emoji="📅",
    max_result_size_chars=100_000
)

if __name__ == "__main__":
    print(query_bupt_xls_schedule(query_date="2026-4-22"))