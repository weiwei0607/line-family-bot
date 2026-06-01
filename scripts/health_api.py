"""Health Api for line-family-bot."""

import requests
import os
import random
import logging
logger = logging.getLogger(__name__)

from api_helpers import (
_retry_http, _check_quota, _apininjas_headers
)


def calc_bmi(height_cm: float, weight_kg: float) -> dict:
    bmi = round(weight_kg / (height_cm / 100) ** 2, 1)
    if bmi < 18.5:
        cat = "體重過輕 😟"
    elif bmi < 24:
        cat = "正常範圍 😊"
    elif bmi < 27:
        cat = "過重 😐"
    elif bmi < 30:
        cat = "輕度肥胖 😬"
    else:
        cat = "中重度肥胖 ⚠️"
    return {"bmi": bmi, "category": cat}

def get_nutrition(query: str) -> list[dict]:
    if not APININJAS_KEY:
        return []
    try:
        r = requests.get("https://api.api-ninjas.com/v1/nutrition",
                         headers=_apininjas_headers(), params={"query": query}, timeout=10)
        if _check_quota(r):
            return [{"_quota": True}]
        return r.json().get("items", [])
    except Exception:
        return []

def search_recipes_by_ingredients(ingredients: str) -> list[dict]:
    try:
        first = ingredients.split(",")[0].split("、")[0].strip()
        r = requests.get(
            "https://www.themealdb.com/api/json/v1/1/filter.php",
            params={"i": first},
            timeout=10,
        )
        meals = r.json().get("meals") or []
        return [{"title": m["strMeal"]} for m in meals[:5]]
    except Exception:
        return []

def get_calories_burned(activity: str, weight_kg: float = 60, duration_min: int = 30) -> list[dict]:
    if not APININJAS_KEY:
        return []
    params = {"activity": activity, "weight": str(weight_kg), "duration": str(duration_min)}
    try:
        r = requests.get("https://api.api-ninjas.com/v1/caloriesburned",
                         headers=_apininjas_headers(), params=params, timeout=10)
        if _check_quota(r):
            return [{"_quota": True}]
        return r.json()
    except Exception:
        return []
