import webbrowser
from urllib.parse import quote_plus
from typing import Dict, Any, Optional
from core.tool import AgentTool


def weather_action(
    parameters: dict,
    player=None,
    session_memory=None,
) -> str:
    city     = parameters.get("city")
    when     = parameters.get("time", "today")  

    if not city or not isinstance(city, str) or not city.strip():
        msg = "Sir, the city is missing for the weather report."
        _log(msg, player)
        return msg

    city = city.strip()
    when = (when or "today").strip()

    search_query  = f"weather in {city} {when}"
    url           = f"https://www.google.com/search?q={quote_plus(search_query)}"

    try:
        opened = webbrowser.open(url)
        if not opened:
            raise RuntimeError("webbrowser.open returned False")
    except Exception as e:
        msg = f"Sir, I couldn't open the browser for the weather report: {e}"
        _log(msg, player)
        return msg

    msg = f"Showing the weather for {city}, {when}, sir."
    _log(msg, player)

    if session_memory:
        try:
            session_memory.set_last_search(query=search_query, response=msg)
        except Exception:
            pass

    return msg


def _log(message: str, player=None) -> None:
    print(f"[Weather] {message}")
    if player:
        try:
            player.write_log(f"AGENT: {message}")
        except Exception:
            pass


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
class WeatherReportTool(AgentTool):
    @property
    def name(self) -> str:
        return "weather_report"

    @property
    def description(self) -> str:
        return "Gives the weather report to user"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "city": {
                    "type": "STRING",
                    "description": "City name"
                }
            },
            "required": [
                "city"
            ]
        }

    def execute(self, parameters: Optional[Dict[str, Any]] = None, **context) -> Any:
        return weather_action(
            parameters=parameters or {},
            player=context.get("player"),
            session_memory=context.get("session_memory"),
        )


ACTION = WeatherReportTool()
TOOL = ACTION.to_tool_dict()
