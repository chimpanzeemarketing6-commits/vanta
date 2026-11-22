#!/usr/bin/env python3
"""Vanta Deck: a game hub for the Steam Deck on SteamOS.

Home, your library with covers and search, a page for every game (Deck Verified, ProtonDB, reviews, news, notes, ratings,
battery life, Proton and launch options), your play calendar and badges, screenshots, storage cleanup, live system stats,
a RAM page that closes background apps, and themes. Works with the touchscreen, the controller (D-pad, A, B, L1/R1) and
a keyboard."""
import math
import os
import queue
import random
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont

from PIL import Image, ImageDraw, ImageFilter, ImageTk

import deck_core as dc
import deck_remote

APP = "Vanta Deck"
VERSION = "1.3"

THEMES = {
    "Vanta": dict(bg="#0a0e17", panel="#121a29", panel2="#1a2438", line="#26324a", text="#eef2fb", muted="#8d99b3",
                  accent="#4f8cff", accent2="#8b5cf6", good="#3ddc97", warn="#ffb547", danger="#ff5d6c", fx="glow"),
    "Midnight": dict(bg="#07080d", panel="#10121b", panel2="#171a26", line="#242838", text="#e8eaf4", muted="#8a8fa8",
                     accent="#7c8cff", accent2="#38bdf8", good="#4ade80", warn="#fbbf24", danger="#f87171", fx=None),
    "Starfield": dict(bg="#04060f", panel="#0d1226", panel2="#141a33", line="#232c52", text="#eef1ff", muted="#959dc6",
                      accent="#818cf8", accent2="#f472b6", good="#4ade80", warn="#fbbf24", danger="#f87171", fx="stars"),
    "Nebula": dict(bg="#0c0820", panel="#130d2b", panel2="#1b1438", line="#2e2458", text="#f1edff", muted="#a49ccc",
                   accent="#a78bfa", accent2="#38bdf8", good="#f472b6", warn="#fbbf24", danger="#fb7185", fx="orbs"),
    "Sakura": dict(bg="#1d0b1a", panel="#26101f", panel2="#321528", line="#4a2142", text="#fff0f7", muted="#d0a3bd",
                   accent="#ff8fc7", accent2="#ffd1e8", good="#86efac", warn="#fcd34d", danger="#fb7185", fx="petals"),
    "Deck Blue": dict(bg="#0e141b", panel="#18212c", panel2="#202c3a", line="#2e3d50", text="#e6edf5", muted="#8fa0b4",
                      accent="#1a9fff", accent2="#66c0f4", good="#5ba32b", warn="#e8b93c", danger="#e0544b", fx=None),
    "OLED": dict(bg="#000000", panel="#0b0b0b", panel2="#141414", line="#262626", text="#f5f5f5", muted="#9a9a9a",
                 accent="#00e0a4", accent2="#4f8cff", good="#00e0a4", warn="#ffc23d", danger="#ff5a5a", fx=None),
    "Daylight": dict(bg="#eef1f6", panel="#ffffff", panel2="#f3f5f9", line="#d9dee8", text="#18202e", muted="#5d677a",
                     accent="#2563eb", accent2="#7c3aed", good="#15803d", warn="#a16207", danger="#dc2626", fx=None, light=True),
    "Aurora": dict(bg="#051216", panel="#0b1d22", panel2="#11272e", line="#1d3a42", text="#e9fbf7", muted="#8fb8b0",
                   accent="#2ee6a6", accent2="#38bdf8", good="#2ee6a6", warn="#facc15", danger="#fb7185", fx="orbs"),
    "Snowfall": dict(bg="#0b1220", panel="#121c2e", panel2="#19253b", line="#28364f", text="#f2f7ff", muted="#9fb0cc",
                     accent="#93c5fd", accent2="#e0f2fe", good="#86efac", warn="#fcd34d", danger="#fca5a5", fx="snow"),
    "Ember": dict(bg="#140806", panel="#1e0d0a", panel2="#28130e", line="#402018", text="#fff1ea", muted="#c9a091",
                  accent="#ff7a3d", accent2="#ffc145", good="#a3e635", warn="#ffc145", danger="#ff4d4d", fx="embers"),
    "Synthwave": dict(bg="#120726", panel="#1b0c36", panel2="#241245", line="#3a1f66", text="#fdf0ff", muted="#b49cd6",
                      accent="#ff3ea5", accent2="#22d3ee", good="#4ade80", warn="#fde047", danger="#fb7185", fx="stars"),
    "Forest": dict(bg="#07110a", panel="#0e1b11", panel2="#142519", line="#213a27", text="#ecf8ee", muted="#94b39b",
                   accent="#9be15d", accent2="#f6e05e", good="#9be15d", warn="#f6e05e", danger="#f87171", fx="fireflies"),
    "Ocean": dict(bg="#04121f", panel="#0a1c2e", panel2="#10263c", line="#1b3a57", text="#e6f4ff", muted="#8bafc9",
                  accent="#22a6f2", accent2="#2dd4bf", good="#2dd4bf", warn="#fbbf24", danger="#f87171", fx=None),
    "Mocha": dict(bg="#17120f", panel="#211a16", panel2="#2b221d", line="#3d322b", text="#f5ece4", muted="#b5a395",
                  accent="#d6a26b", accent2="#e8c9a0", good="#a3c47a", warn="#e8b04a", danger="#e06c5a", fx=None),
    "Mono": dict(bg="#0d0d0f", panel="#161619", panel2="#1e1e22", line="#2c2c31", text="#f2f2f2", muted="#9a9aa2",
                 accent="#f2f2f2", accent2="#9a9aa2", good="#d4d4d4", warn="#d4d4d4", danger="#ff6b6b", fx=None),
    # ---- every other theme from Vanta for Windows (same colors; gradients and animations where they exist)
    'Vanta OLED': {'bg': '#000000', 'panel': '#0c0d10', 'panel2': '#15171d', 'line': '#202330', 'text': '#f3f5fa', 'muted': '#878ea1', 'accent': '#8b7bff', 'accent2': '#4fd1ff', 'good': '#3ddc97', 'warn': '#ffb84d', 'danger': '#ff5c6c', 'fx': None},
    'OLED Black': {'bg': '#000000', 'panel': '#0b0b0b', 'panel2': '#151515', 'line': '#262626', 'text': '#f2f2f2', 'muted': '#8a8a8a', 'accent': '#00c8ff', 'accent2': '#b36bff', 'good': '#2ee59d', 'warn': '#ffbf3c', 'danger': '#ff4d5e', 'fx': None},
    'Phosphor': {'bg': '#020a04', 'panel': '#06150a', 'panel2': '#0b2212', 'line': '#14432a', 'text': '#b4ffc8', 'muted': '#56a872', 'accent': '#3cff78', 'accent2': '#78ffd2', 'good': '#3cff78', 'warn': '#ffd23c', 'danger': '#ff5a50', 'fx': None},
    'Amber': {'bg': '#0d0800', 'panel': '#1a1100', 'panel2': '#251800', 'line': '#4a3200', 'text': '#ffd98a', 'muted': '#a8823a', 'accent': '#ffb000', 'accent2': '#ffe680', 'good': '#d6ff6a', 'warn': '#ff8c1a', 'danger': '#ff5a3c', 'fx': None},
    'Cyberpunk': {'bg': '#0d0221', 'panel': '#170536', 'panel2': '#230a4c', 'line': '#3c1b70', 'text': '#f4ecff', 'muted': '#9d89c4', 'accent': '#ff2bd6', 'accent2': '#00e5ff', 'good': '#00ffa3', 'warn': '#ffe600', 'danger': '#ff3b5c', 'fx': None},
    'Glacier': {'bg': '#0d1922', 'panel': '#132533', 'panel2': '#1a3143', 'line': '#284a62', 'text': '#e6f5ff', 'muted': '#8fb1c9', 'accent': '#7fd6ff', 'accent2': '#a8b8ff', 'good': '#7fffcf', 'warn': '#ffd27f', 'danger': '#ff7f8f', 'fx': None},
    'Rose': {'bg': '#170a10', 'panel': '#22101a', 'panel2': '#2e1623', 'line': '#4c2539', 'text': '#ffe9f1', 'muted': '#c08da3', 'accent': '#ff6f9f', 'accent2': '#ffb38a', 'good': '#7fe0b0', 'warn': '#ffd27a', 'danger': '#ff4d4d', 'fx': None},
    'High Contrast': {'bg': '#000000', 'panel': '#000000', 'panel2': '#121212', 'line': '#ffffff', 'text': '#ffffff', 'muted': '#e6e6e6', 'accent': '#ffd400', 'accent2': '#00e5ff', 'good': '#3dff7a', 'warn': '#ffd400', 'danger': '#ff4d4d', 'fx': None},
    'Sandstone': {'bg': '#f4efe6', 'panel': '#fffaf2', 'panel2': '#f1e9db', 'line': '#dccfb8', 'text': '#2b2116', 'muted': '#7a6a55', 'accent': '#c2581b', 'accent2': '#2f7d6d', 'good': '#2e7d32', 'warn': '#a66a00', 'danger': '#b3261e', 'fx': None, 'light': True},
    'Lavender': {'bg': '#f3f0fb', 'panel': '#ffffff', 'panel2': '#f2eefb', 'line': '#dcd3f0', 'text': '#1e1633', 'muted': '#6b5f8a', 'accent': '#6c47ff', 'accent2': '#e0457b', 'good': '#1b8a5a', 'warn': '#a86b00', 'danger': '#c9184a', 'fx': None, 'light': True},
    'Sunset': {'bg': '#2f1438', 'panel': '#1c0f24', 'panel2': '#2a1733', 'line': '#4a2a52', 'text': '#fff0ea', 'muted': '#c9a3b0', 'accent': '#ff8a5c', 'accent2': '#ffc15e', 'good': '#7ee8a7', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': None, 'grad': ['#1b0f2e', '#4a1a3f', '#7a2f2f'], 'angle': 120},
    'Deep Sea': {'bg': '#071a33', 'panel': '#06142a', 'panel2': '#0b1f3a', 'line': '#163a5c', 'text': '#e0f4ff', 'muted': '#7fa6c2', 'accent': '#22d3ee', 'accent2': '#60a5fa', 'good': '#5eead4', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': 'bubbles', 'grad': ['#020617', '#0b2747', '#04303a'], 'angle': 100},
    'Twilight': {'bg': '#22205a', 'panel': '#111735', 'panel2': '#1a2048', 'line': '#323a75', 'text': '#eef2ff', 'muted': '#a5b0db', 'accent': '#a5b4fc', 'accent2': '#f0abfc', 'good': '#5eead4', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': None, 'grad': ['#0f172a', '#312e81', '#4c1d95'], 'angle': 140},
    'Emerald': {'bg': '#053b2c', 'panel': '#03221a', 'panel2': '#073326', 'line': '#145a45', 'text': '#e7fff5', 'muted': '#86c9b0', 'accent': '#34d399', 'accent2': '#a3e635', 'good': '#5eead4', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': None, 'grad': ['#021a12', '#064e3b', '#022c22'], 'angle': 110},
    'Peach': {'bg': '#fff0ee', 'panel': '#ffffff', 'panel2': '#fff6f2', 'line': '#f1d9d4', 'text': '#2a1a1f', 'muted': '#8a6b70', 'accent': '#ff6b4a', 'accent2': '#8b5cf6', 'good': '#15803d', 'warn': '#b45309', 'danger': '#dc2626', 'fx': None, 'light': True, 'grad': ['#fff4e6', '#ffe3e3', '#f3e8ff'], 'angle': 125},
    'Mint': {'bg': '#e6f8f8', 'panel': '#ffffff', 'panel2': '#f3fbf8', 'line': '#cfe8de', 'text': '#0f2a22', 'muted': '#5b7b70', 'accent': '#10b981', 'accent2': '#0ea5e9', 'good': '#059669', 'warn': '#b45309', 'danger': '#dc2626', 'fx': None, 'light': True, 'grad': ['#ecfdf5', '#e0f2fe'], 'angle': 135},
    'Flow': {'bg': '#241a5a', 'panel': '#0d1230', 'panel2': '#161b42', 'line': '#2c3168', 'text': '#eef0ff', 'muted': '#9aa3d6', 'accent': '#7dd3fc', 'accent2': '#f0abfc', 'good': '#5eead4', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': 'orbs', 'grad': ['#0f1d4a', '#3b1c7a', '#6b1747', '#0f1d4a'], 'angle': 135},
    'Matrix': {'bg': '#000500', 'panel': '#010d03', 'panel2': '#03170a', 'line': '#0c3a18', 'text': '#b6ffc8', 'muted': '#4f9f63', 'accent': '#22ff66', 'accent2': '#9dffb8', 'good': '#22ff66', 'warn': '#e6ff4d', 'danger': '#ff5050', 'fx': 'rain'},
    'Retro Grid': {'bg': '#1d0638', 'panel': '#140433', 'panel2': '#1f0a47', 'line': '#3c1a70', 'text': '#fdf0ff', 'muted': '#b392c9', 'accent': '#ff2bd6', 'accent2': '#29d6ff', 'good': '#3cf5c5', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': 'grid', 'grad': ['#0d0221', '#2d0a4e', '#3a0b45'], 'angle': 90},
    'Lava': {'bg': '#2a0801', 'panel': '#1a0703', 'panel2': '#2a0e06', 'line': '#4f1d0e', 'text': '#ffe9dc', 'muted': '#c28b74', 'accent': '#ff6a1a', 'accent2': '#ffc23d', 'good': '#a3e635', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': 'embers', 'grad': ['#1a0400', '#3a0c02', '#120200'], 'angle': 95},
    'CRT': {'bg': '#020a04', 'panel': '#06150a', 'panel2': '#0b2212', 'line': '#14432a', 'text': '#b4ffc8', 'muted': '#56a872', 'accent': '#3cff78', 'accent2': '#78ffd2', 'good': '#3cff78', 'warn': '#ffd23c', 'danger': '#ff5a50', 'fx': 'scan'},
    'Minimal Dark': {'bg': '#0f0f10', 'panel': '#0f0f10', 'panel2': '#18181b', 'line': '#2c2c31', 'text': '#f4f4f5', 'muted': '#8b8b94', 'accent': '#f4f4f5', 'accent2': '#a1a1aa', 'good': '#86efac', 'warn': '#e0b04a', 'danger': '#f87171', 'fx': None},
    'Minimal Light': {'bg': '#fafafa', 'panel': '#fafafa', 'panel2': '#f1f1f2', 'line': '#dcdce0', 'text': '#18181b', 'muted': '#71717a', 'accent': '#18181b', 'accent2': '#52525b', 'good': '#15803d', 'warn': '#a16207', 'danger': '#dc2626', 'fx': None, 'light': True},
    'Terminal': {'bg': '#000000', 'panel': '#000000', 'panel2': '#0a120b', 'line': '#1f3a24', 'text': '#c8ffd4', 'muted': '#5f9a6b', 'accent': '#3cff78', 'accent2': '#7ff0ff', 'good': '#3cff78', 'warn': '#ffd23c', 'danger': '#ff5a50', 'fx': None},
    'Fjord': {'bg': '#2e3440', 'panel': '#2e3440', 'panel2': '#3b4252', 'line': '#4c566a', 'text': '#eceff4', 'muted': '#a3acbd', 'accent': '#88c0d0', 'accent2': '#b48ead', 'good': '#a3be8c', 'warn': '#ebcb8b', 'danger': '#bf616a', 'fx': None},
    'Paper': {'bg': '#f6f1e7', 'panel': '#f6f1e7', 'panel2': '#ece5d6', 'line': '#d6ccb8', 'text': '#2b2620', 'muted': '#7a7062', 'accent': '#2b2620', 'accent2': '#9c4221', 'good': '#2f6b3a', 'warn': '#a16207', 'danger': '#b42318', 'fx': None, 'light': True},
    'High Contrast Light': {'bg': '#ffffff', 'panel': '#ffffff', 'panel2': '#f0f0f0', 'line': '#000000', 'text': '#000000', 'muted': '#1a1a1a', 'accent': '#0033cc', 'accent2': '#8a0099', 'good': '#006b1f', 'warn': '#7a4a00', 'danger': '#b00000', 'fx': None, 'light': True},
    'Fireflies': {'bg': '#0b1d14', 'panel': '#0a1a12', 'panel2': '#10261b', 'line': '#1f4030', 'text': '#f2ffe9', 'muted': '#9ab8a2', 'accent': '#c8f560', 'accent2': '#ffd166', 'good': '#5eead4', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': 'fireflies', 'grad': ['#06120c', '#0c2418', '#14140a'], 'angle': 100},
    'Sakura Day': {'bg': '#fdeef4', 'panel': '#ffffff', 'panel2': '#fff5f9', 'line': '#f2d3e1', 'text': '#2b1622', 'muted': '#8a6577', 'accent': '#e0458a', 'accent2': '#8b5cf6', 'good': '#15803d', 'warn': '#a16207', 'danger': '#dc2626', 'fx': 'petals', 'light': True, 'grad': ['#fff1f6', '#fde4ef', '#f3e8ff'], 'angle': 130},
    'Confetti': {'bg': '#160f33', 'panel': '#120c2a', 'panel2': '#1b1438', 'line': '#30285e', 'text': '#f5f3ff', 'muted': '#a7a2cf', 'accent': '#ffcc33', 'accent2': '#ff5fa2', 'good': '#4ade80', 'warn': '#ffcc33', 'danger': '#ff5d73', 'fx': 'confetti', 'grad': ['#0e0b24', '#1d1240', '#0b1630'], 'angle': 120},
    'Tide': {'bg': '#05263a', 'panel': '#04192a', 'panel2': '#082438', 'line': '#14415f', 'text': '#e3f6ff', 'muted': '#86aec6', 'accent': '#38bdf8', 'accent2': '#2dd4bf', 'good': '#5eead4', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': 'waves', 'grad': ['#031524', '#06304a', '#03202f'], 'angle': 95},
    'Lagoon': {'bg': '#033532', 'panel': '#032523', 'panel2': '#073330', 'line': '#145550', 'text': '#e6fffb', 'muted': '#86c2b9', 'accent': '#5eead4', 'accent2': '#93c5fd', 'good': '#5eead4', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': 'waves', 'grad': ['#022424', '#04403d', '#0b2a3a'], 'angle': 100},
    'Lava Lamp': {'bg': '#240809', 'panel': '#1a0607', 'panel2': '#280c0d', 'line': '#4a1a1c', 'text': '#fff0e8', 'muted': '#c9968a', 'accent': '#ff6b3d', 'accent2': '#ffb02e', 'good': '#ff3d7f', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': 'orbs', 'grad': ['#1a0505', '#2a0a0f', '#1a0a02'], 'angle': 110},
    'Northern Lights': {'bg': '#04141d', 'panel': '#041119', 'panel2': '#081c26', 'line': '#173847', 'text': '#eafff8', 'muted': '#89b3aa', 'accent': '#4ade80', 'accent2': '#e879f9', 'good': '#22d3ee', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': 'aurora', 'grad': ['#020b14', '#04202a', '#12082a'], 'angle': 115},
    'Blizzard': {'bg': '#dde9f3', 'panel': '#ffffff', 'panel2': '#f2f7fb', 'line': '#c7d8e6', 'text': '#0f1d2a', 'muted': '#5a6f82', 'accent': '#2563eb', 'accent2': '#0891b2', 'good': '#15803d', 'warn': '#a16207', 'danger': '#dc2626', 'fx': 'snow', 'light': True, 'grad': ['#e8f1f8', '#d6e6f3'], 'angle': 90},
    'Monsoon': {'bg': '#0f1b29', 'panel': '#0c1622', 'panel2': '#132233', 'line': '#24384f', 'text': '#e6f0fb', 'muted': '#8ea3ba', 'accent': '#60a5fa', 'accent2': '#a5b4fc', 'good': '#5eead4', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': 'rain', 'grad': ['#0a121c', '#122133', '#0b1622'], 'angle': 95},
    'Galaxy': {'bg': '#070a1f', 'panel': '#080b20', 'panel2': '#0f1430', 'line': '#222a55', 'text': '#eef1ff', 'muted': '#9aa2cc', 'accent': '#818cf8', 'accent2': '#f472b6', 'good': '#5eead4', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': 'stars', 'grad': ['#02030a', '#0a0f2e', '#170a2e'], 'angle': 135},
    'Prism': {'bg': '#1f1a3a', 'panel': '#120f24', 'panel2': '#1b1733', 'line': '#332d5c', 'text': '#f6f4ff', 'muted': '#aaa6cf', 'accent': '#f0abfc', 'accent2': '#67e8f9', 'good': '#5eead4', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': 'orbs', 'grad': ['#3a0d4a', '#0d2f5c', '#0b4a45', '#4a3a0b', '#4a0d2a', '#3a0d4a'], 'angle': 135},
    'Ocean Flow': {'bg': '#062a48', 'panel': '#04182c', 'panel2': '#08223a', 'line': '#17405f', 'text': '#e3f4ff', 'muted': '#88aac4', 'accent': '#22d3ee', 'accent2': '#818cf8', 'good': '#5eead4', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': 'orbs', 'grad': ['#031a33', '#05445e', '#0a2a5c', '#031a33'], 'angle': 120},
    'Vaporwave': {'bg': '#2a0b4a', 'panel': '#1c0838', 'panel2': '#260d48', 'line': '#45207a', 'text': '#fff0fb', 'muted': '#c39bd6', 'accent': '#2ef2ff', 'accent2': '#ff71ce', 'good': '#05ffa1', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': 'grid', 'grad': ['#1a0633', '#3d0f5c', '#0f3a5c'], 'angle': 90},
    'Dusk': {'bg': '#2a2240', 'panel': '#151a2c', 'panel2': '#1e2238', 'line': '#363a5a', 'text': '#f3efff', 'muted': '#a9a4c6', 'accent': '#fb923c', 'accent2': '#c084fc', 'good': '#5eead4', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': None, 'grad': ['#141e30', '#35234a', '#5c2a3a'], 'angle': 110},
    'Citrus': {'bg': '#fbf8e4', 'panel': '#ffffff', 'panel2': '#fbfaf0', 'line': '#e7e3c3', 'text': '#1f2410', 'muted': '#6b6f4f', 'accent': '#65a30d', 'accent2': '#ea580c', 'good': '#15803d', 'warn': '#a16207', 'danger': '#dc2626', 'fx': None, 'light': True, 'grad': ['#fffbe6', '#ecfccb', '#fff1e0'], 'angle': 125},
    'Berry': {'bg': '#2c0a33', 'panel': '#1c0721', 'panel2': '#280d2e', 'line': '#4a1a50', 'text': '#ffeefa', 'muted': '#c79bc0', 'accent': '#f43f9e', 'accent2': '#a78bfa', 'good': '#5eead4', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': None, 'grad': ['#1a0620', '#3b0a3a', '#200a33'], 'angle': 130},
    'Steel': {'bg': '#1a1f26', 'panel': '#13171c', 'panel2': '#1c2128', 'line': '#2f3640', 'text': '#eef2f6', 'muted': '#94a0ae', 'accent': '#7dd3fc', 'accent2': '#cbd5e1', 'good': '#5eead4', 'warn': '#ffd166', 'danger': '#ff5d73', 'fx': None, 'grad': ['#111418', '#1f252d', '#14181d'], 'angle': 100},
    'Nightshade': {'bg': '#191a21', 'panel': '#21222c', 'panel2': '#2a2c38', 'line': '#3a3c4e', 'text': '#f8f8f2', 'muted': '#9ea2bd', 'accent': '#bd93f9', 'accent2': '#ff79c6', 'good': '#50fa7b', 'warn': '#f1fa8c', 'danger': '#ff5555', 'fx': None},
    'Solar Dark': {'bg': '#002b36', 'panel': '#073642', 'panel2': '#0b3f4c', 'line': '#1d5563', 'text': '#eee8d5', 'muted': '#93a1a1', 'accent': '#2aa198', 'accent2': '#b58900', 'good': '#859900', 'warn': '#cb4b16', 'danger': '#dc322f', 'fx': None},
    'Campfire': {'bg': '#1d2021', 'panel': '#282828', 'panel2': '#32302f', 'line': '#504945', 'text': '#ebdbb2', 'muted': '#a89984', 'accent': '#fe8019', 'accent2': '#fabd2f', 'good': '#b8bb26', 'warn': '#fabd2f', 'danger': '#fb4934', 'fx': None},
    'Coffee': {'bg': '#1b1411', 'panel': '#251c18', 'panel2': '#2f2420', 'line': '#4a3a33', 'text': '#f3e7dc', 'muted': '#b09a8a', 'accent': '#d4a373', 'accent2': '#e9c46a', 'good': '#90be6d', 'warn': '#e9c46a', 'danger': '#e76f51', 'fx': None},
    'Matcha': {'bg': '#f1f5ea', 'panel': '#fbfdf7', 'panel2': '#eef3e4', 'line': '#d5dfc3', 'text': '#1c2614', 'muted': '#5f6d52', 'accent': '#4d7c0f', 'accent2': '#b45309', 'good': '#15803d', 'warn': '#a16207', 'danger': '#dc2626', 'fx': None, 'light': True},
    'Latte': {'bg': '#eff1f5', 'panel': '#ffffff', 'panel2': '#e6e9ef', 'line': '#ccd0da', 'text': '#4c4f69', 'muted': '#7c7f93', 'accent': '#8839ef', 'accent2': '#fe640b', 'good': '#15803d', 'warn': '#a16207', 'danger': '#dc2626', 'fx': None, 'light': True},
    'Neon Night': {'bg': '#0a0a12', 'panel': '#12121e', 'panel2': '#1a1a2b', 'line': '#2b2b45', 'text': '#e9e9ff', 'muted': '#8f8fb8', 'accent': '#39ff14', 'accent2': '#ff2079', 'good': '#39ff14', 'warn': '#ffe600', 'danger': '#ff3355', 'fx': None},
}
TABS = [("home", "Home"), ("library", "Library"), ("play", "Play"), ("shots", "Shots"), ("storage", "Storage"), ("system", "System"),
        ("tools", "Tools"), ("settings", "Settings")]
BADGES = [("first", "First session", "Play a game with Vanta open"), ("marathon", "Marathon", "One session of 3 hours"),
          ("owl", "Night owl", "Start a game after midnight"), ("streak7", "Week streak", "Play 7 days in a row"),
          ("explorer", "Explorer", "Play 10 different games"), ("finisher", "Finisher", "Finish 3 games"),
          ("critic", "Critic", "Rate 5 games"), ("century", "Centurion", "100 hours in Steam")]


def mix(a, b, t):
    a, b = a.lstrip("#"), b.lstrip("#")
    ca = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(ca, cb))


def on_color(hexc):
    h = hexc.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#0b0f17" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#ffffff"


class RemoteBridge:
    """What the phone app server may ask of Vanta Deck."""

    def __init__(self, app):
        self.app = app

    @property
    def pin(self):
        return self.app.cfg["remote_pin"]

    def state(self):
        return self.app.state()

    def action(self, a, v):
        return self.app.action(a, v)

    def cover(self, gid):
        g = self.app.game(gid)
        return g["cover"] if g and g["cover"] else None

    def shots(self):
        return list(self.app.shots or [])


class App:
    def __init__(self):
        self.cfg = dc.Config()
        self.root = tk.Tk()
        self.root.title(APP)
        self.root.configure(bg="#000000")
        W, H = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        geo = os.environ.get("VANTA_GEOMETRY")
        if geo:
            self.root.geometry(geo)
        else:
            self.root.geometry(f"{min(W, 1280)}x{min(H, 800)}+0+0")
            if W <= 1366 or os.environ.get("SteamDeck") or os.environ.get("SteamGamepadUI") or os.environ.get("GAMESCOPE_WAYLAND_DISPLAY"):
                self.root.attributes("-fullscreen", True)
        self.c = tk.Canvas(self.root, highlightthickness=0, bd=0, bg="#000000")
        self.c.pack(fill="both", expand=True)
        fams = set(tkfont.families(self.root))
        self.family = next((f for f in ("Noto Sans", "Cantarell", "Inter", "DejaVu Sans", "Liberation Sans") if f in fams), "TkDefaultFont")
        self.fonts = {}
        self.imgs = {}
        self.img_keep = []
        self.regions = []
        self.focus = None
        self.focus_visible = False
        self.pressed = None
        self.tab = self.cfg["start_tab"] if self.cfg["start_tab"] in dict(TABS) else "home"
        self.page = None          # an overlay page: ("game", gid)
        self.scroll = {}
        self.library = None
        self.steam = None
        self.sensors = dc.Sensors()
        self.stats = {}
        self.toast = None
        self.jobs = queue.Queue()
        self.data = {}            # per-game fetched info: news, reviews, deck, protondb
        self.cleanup = None
        self.running = {}         # appid -> start time
        self.armed = {}
        self.entry = None
        self.shots = None         # Steam screenshots, newest first
        self.ram = None           # (memory info, apps) for the RAM page
        self.search = ""
        self.docked = False
        self.boosted = False      # Game Boost already ran for the games running now
        self.remote = None
        self.startup = None
        self.backups = None
        self.theme_slot = "main"
        self.update = None        # newest release on GitHub (see deck_core.check_update)
        self.update_state = None  # None, "checking", "downloading", (0..1 progress), "error: …", "latest"
        self.theme_filter = "all"
        self.fx = None
        self.fx_cost = 0.01
        self.drag = None
        self.W = self.H = 0
        self.c.bind("<Configure>", lambda e: self.redraw())
        self.c.bind("<ButtonPress-1>", self.on_press)
        self.c.bind("<B1-Motion>", self.on_drag)
        self.c.bind("<ButtonRelease-1>", self.on_release)
        self.c.bind("<MouseWheel>", lambda e: self.wheel(-1 if e.delta > 0 else 1))
        self.c.bind("<Button-4>", lambda e: self.wheel(-1))
        self.c.bind("<Button-5>", lambda e: self.wheel(1))
        self.root.bind("<Key>", self.on_key)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.joy = dc.Joystick(lambda b: self.jobs.put(("pad", b)))
        self.wake_paused(quiet=True)  # apps left frozen if Vanta was closed mid-game
        if self.cfg["remote"]:
            self.root.after(500, lambda: self.set_remote(True, quiet=True))
        if self.cfg["update_auto"] and time.time() - self.cfg["update_last"] > 6 * 3600:
            self.root.after(6000, lambda: self.check_update(quiet=True))
        threading.Thread(target=self.load_library, daemon=True).start()
        self.root.after(50, self.pump)
        self.root.after(200, self.tick)
        self.root.after(400, self.fx_loop)

    # ------------------------------------------------------------------ basics
    @property
    def t(self):
        return THEMES.get(self.theme_name(), THEMES["Vanta"])

    def theme_name(self):
        if self.cfg["day_night"]:
            a, b = self.cfg["day_hours"]
            if a <= time.localtime().tm_hour < b:
                return self.cfg["day_theme"]
        return self.cfg["theme"]

    def font(self, size, bold=False):
        key = (round(size), bold)
        if key not in self.fonts:
            self.fonts[key] = tkfont.Font(family=self.family, size=-max(8, round(size)), weight="bold" if bold else "normal")
        return self.fonts[key]

    def background(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def call(self, fn):
        self.jobs.put(("call", fn))

    def pump(self):
        try:
            while True:
                kind, v = self.jobs.get_nowait()
                if kind == "call":
                    v()
                elif kind == "pad" and self.root.focus_displayof() is not None:
                    self.on_pad(v)
        except queue.Empty:
            pass
        self.root.after(30, self.pump)

    def show_toast(self, text):
        self.toast = (text, time.time() + 2.6)
        self.redraw()
        self.root.after(2700, self.redraw)

    def quit(self):
        self.wake_paused(quiet=True)
        if self.remote:
            self.remote.stop()
        try:
            self.cfg.save()
        except OSError:
            pass
        self.joy.stop = True
        self.root.destroy()

    def confirm(self, key, fn, msg):
        if self.armed.get(key, 0) > time.time():
            self.armed.pop(key, None)
            fn()
        else:
            self.armed[key] = time.time() + 3
            self.show_toast(msg)
            self.root.after(3100, self.redraw)
        self.redraw()

    def is_armed(self, key):
        return self.armed.get(key, 0) > time.time()

    # ------------------------------------------------------------------ data
    def load_library(self):
        try:
            games, steam = dc.scan_library()
        except Exception:
            games, steam = [], None
        if self.cfg["stores"]:
            for fn in (dc.heroic_games, dc.lutris_games):
                try:
                    games += fn()
                except Exception:
                    pass
        self.call(lambda: self.library_ready(games, steam))

    def library_ready(self, games, steam):
        self.library, self.steam = games, steam
        self.load_shots()
        self.redraw()
        if self.cfg["art_fetch"]:
            todo = [g for g in games if g["source"] == "Steam" and (not g["cover"] or not g["hero"])]
            other = [g for g in games if g.get("art_url") and not g["cover"] and str(g["art_url"]).startswith("https://")]

            def work():
                for g in other[:200]:
                    if dc.download(g["art_url"], g["art_path"]):
                        g["cover"] = g["art_path"]
                        self.call(self.redraw)
                for g in todo[:300]:
                    if not g["cover"]:
                        p = dc.fetch_art(g["appid"], "cover")
                        if p:
                            g["cover"] = p
                            self.call(self.redraw)
                    if not g["hero"]:
                        p = dc.fetch_art(g["appid"], "hero")
                        if p:
                            g["hero"] = p
                    time.sleep(0.05)
            self.background(work)

    def load_shots(self):
        udir = (self.steam or {}).get("udir")

        def work():
            try:
                res = dc.screenshots(udir)
            except Exception:
                res = []
            self.call(lambda: (setattr(self, "shots", res), self.redraw()))
        self.background(work)

    def game_by_appid(self, aid):
        return next((g for g in self.library or [] if g["appid"] == str(aid)), None)

    def game(self, gid):
        return next((g for g in self.library or [] if g["id"] == gid), None)

    def recent(self):
        lib = list(self.library or [])
        lib.sort(key=lambda g: (g["last"], g["minutes"]), reverse=True)
        return lib

    def home_game(self):
        g = self.game(self.cfg["home_sel"]) if self.cfg["home_sel"] else None
        if g:
            return g
        q = [self.game(i) for i in self.cfg["queue"]]
        q = [x for x in q if x]
        r = self.recent()
        return (r[0] if r and r[0]["last"] else (q[0] if q else (r[0] if r else None)))

    def fetch_info(self, g):
        if g["source"] != "Steam" or g["id"] in self.data:
            return
        info = self.data[g["id"]] = {}

        def work():
            for key, fn in (("deck", dc.deck_compat), ("proton", dc.protondb_tier), ("reviews", dc.steam_reviews),
                            ("news", dc.steam_news)):
                try:
                    info[key] = fn(g["appid"])
                except Exception:
                    info[key] = None
                self.call(self.redraw)
        self.background(work)

    def track(self):
        """Notice games starting and stopping, and keep a session for each."""
        def work():
            try:
                ids = dc.running_appids()
            except Exception:
                return
            self.call(lambda: self.track_done(ids))
        self.background(work)

    def track_done(self, ids):
        now = time.time()
        was = bool(self.running)
        for aid in ids:
            self.running.setdefault(aid, now)
        if self.running and not was and self.cfg["boost_auto"] and not self.boosted:
            self.boost(auto=True)
        if not ids and was:
            self.boosted = False
            self.root.after(3000, self.wake_paused)
        for aid in [a for a in self.running if a not in ids]:
            start = self.running.pop(aid)
            dur = now - start
            if dur >= 60 and self.cfg["guest"]:
                continue  # guest mode: nothing is remembered
            if dur >= 60:
                g = next((x for x in self.library or [] if x["appid"] == aid), None)
                self.cfg["sessions"] = ([{"appid": aid, "name": g["name"] if g else f"App {aid}", "start": start, "dur": dur}]
                                        + self.cfg["sessions"])[:1000]
                if g:
                    g["last"] = int(now)
                    g["minutes"] += int(dur / 60)
                    self.show_toast(f"{g['name']}: played {dc.fmt_duration(dur)}")
                try:
                    self.cfg.save()
                except OSError:
                    pass

    def sample_power(self):
        """While a game runs on battery, remember how much power it draws: that gives its battery life."""
        b = self.stats.get("batt") or {}
        if not self.running or b.get("status") != "Discharging" or not b.get("watts") or b["watts"] < 1:
            return
        aid = next(iter(self.running))
        pw = dict(self.cfg["power"])
        tot, n = pw.get(aid, [0.0, 0])
        if n > 36000:  # keep it following recent play
            tot, n = tot / 2, n // 2
        pw[aid] = [tot + b["watts"], n + 1]
        self.cfg["power"] = pw

    def played_since(self, since):
        tot = sum(x["start"] + x["dur"] - max(x["start"], since) for x in self.cfg["sessions"] if x["start"] + x["dur"] > since)
        tot += sum(time.time() - max(s, since) for s in self.running.values())
        return tot

    def week_start(self):
        lt = time.localtime()
        return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday - lt.tm_wday, 0, 0, 0, 0, 0, -1))

    def month_start(self):
        lt = time.localtime()
        return time.mktime((lt.tm_year, lt.tm_mon, 1, 0, 0, 0, 0, 0, -1))

    def played_today(self):
        lt = time.localtime()
        midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
        tot = sum(x["start"] + x["dur"] - max(x["start"], midnight) for x in self.cfg["sessions"] if x["start"] + x["dur"] > midnight)
        tot += sum(time.time() - max(s, midnight) for s in self.running.values())
        return tot

    def streak(self):
        import datetime as dt
        days = {time.strftime("%Y-%m-%d", time.localtime(x["start"])) for x in self.cfg["sessions"]}
        if self.running:
            days.add(time.strftime("%Y-%m-%d"))
        d = dt.date.today()
        if d.isoformat() not in days:
            d -= dt.timedelta(days=1)
        n = 0
        while d.isoformat() in days:
            n += 1
            d -= dt.timedelta(days=1)
        return n

    # ------------------------------------------------------------------ loops
    def tick(self):
        self.stats = self.sensors.sample()
        n = getattr(self, "_ticks", 0) + 1
        self._ticks = n
        if n % 4 == 0 and self.library is not None:
            self.track()
        if not self.cfg["guest"]:
            self.sample_power()
        if n % 5 == 0:
            self.background(self.check_env)
        if not self.page and self.tab in ("system", "home", "play") or n % 15 == 0:
            self.redraw()
        if n % 60 == 0:
            try:
                self.cfg.save()
            except OSError:
                pass
        self.root.after(1000, self.tick)

    # ------------------------------------------------------------------ drawing primitives
    def rr(self, x0, y0, x1, y1, r, fill, outline="", width=1, tags=()):
        r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
        if r < 1:
            return self.c.create_rectangle(x0, y0, x1, y1, fill=fill, outline=outline, width=width, tags=tags)
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r,
               x0, y0 + r, x0, y0]
        return self.c.create_polygon(pts, smooth=True, fill=fill, outline=outline, width=width, tags=tags)

    def text(self, x, y, s, font, fill, anchor="nw", maxw=None, tags=()):
        s = str(s)
        if maxw and font.measure(s) > maxw:
            while s and font.measure(s + "…") > maxw:
                s = s[:-1]
            s += "…"
        return self.c.create_text(x, y, text=s, font=font, fill=fill, anchor=anchor, tags=tags)

    def wrap(self, s, font, maxw):
        words, lines, cur = str(s).split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if font.measure(t) <= maxw:
                cur = t
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    def region(self, rid, x0, y0, x1, y1, tap, scroll=None):
        self.regions.append({"id": rid, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "tap": tap, "scroll": scroll})

    def button(self, rid, x0, y0, x1, y1, label, tap, style="normal", size=15):
        T, k = self.t, self.k
        fill = {"accent": T["accent"], "danger": T["danger"], "normal": T["panel2"], "ghost": mix(T["panel2"], T["bg"], 0.3)}[style]
        if self.pressed == rid:
            fill = mix(fill, "#000000" if not T.get("light") else "#ffffff", 0.2)
        self.rr(x0, y0, x1, y1, (y1 - y0) / 2, fill)
        fg = on_color(fill) if style in ("accent", "danger") else T["text"]
        self.text((x0 + x1) / 2, (y0 + y1) / 2, label, self.font(size * k, True), fg, anchor="center", maxw=x1 - x0 - 16 * k)
        self.region(rid, x0, y0, x1, y1, tap)

    def image(self, path, w, h, radius=0, cover=True):
        key = (path, int(w), int(h), int(radius))
        if key in self.imgs:
            return self.imgs[key]
        try:
            im = Image.open(path)
            if im.format == "JPEG":
                im.draft("RGB", (int(w), int(h)))
            im = im.convert("RGB")
            if cover:
                sc = max(w / im.width, h / im.height)
                im = im.resize((max(1, int(im.width * sc + 0.5)), max(1, int(im.height * sc + 0.5))), Image.LANCZOS)
                l, t_ = (im.width - int(w)) // 2, (im.height - int(h)) // 2
                im = im.crop((l, t_, l + int(w), t_ + int(h)))
            if radius:  # see-through corners, so covers sit on any background
                m = Image.new("L", im.size, 0)
                ImageDraw.Draw(m).rounded_rectangle((0, 0, im.width - 1, im.height - 1), int(radius), fill=255)
                im = im.convert("RGBA")
                im.putalpha(m)
            ph = ImageTk.PhotoImage(im)
        except Exception:
            ph = None
        if len(self.imgs) > 400:
            self.imgs.clear()
        self.imgs[key] = ph
        return ph

    def hero_image(self, path, w, h):
        key = ("hero", path, int(w), int(h), self.cfg["theme"])
        if key in self.imgs:
            return self.imgs[key]
        try:
            im = Image.open(path).convert("RGB")
            sc = max(w / im.width, h / im.height)
            im = im.resize((int(im.width * sc + 1), int(im.height * sc + 1)), Image.LANCZOS)
            im = im.crop((0, 0, int(w), int(h)))
            bg = tuple(int(self.t["bg"][i:i + 2], 16) for i in (1, 3, 5))
            fade = Image.new("L", (1, int(h)))
            for y in range(int(h)):
                fade.putpixel((0, y), int(255 * min(1, max(0, (y / h - 0.35) / 0.65)) ** 1.4))
            fade = fade.resize((int(w), int(h)))
            im = Image.composite(Image.new("RGB", im.size, bg), im, fade)
            ph = ImageTk.PhotoImage(im)
        except Exception:
            ph = None
        self.imgs[key] = ph
        return ph

    def placeholder_cover(self, g, x0, y0, x1, y1):
        T, k = self.t, self.k
        h = sum(ord(ch) for ch in g["name"]) % 360
        import colorsys
        r, gg, b = colorsys.hls_to_rgb(h / 360, 0.32, 0.45)
        col = "#%02x%02x%02x" % (int(r * 255), int(gg * 255), int(b * 255))
        self.rr(x0, y0, x1, y1, 12 * k, col)
        self.rr(x0, y0 + (y1 - y0) * 0.55, x1, y1, 12 * k, mix(col, "#000000", 0.35))
        f = self.font(15 * k, True)
        lines = self.wrap(g["name"], f, x1 - x0 - 20 * k)[:3]
        for i, ln in enumerate(lines):
            self.text(x0 + 10 * k, y1 - 14 * k - (len(lines) - i) * f.metrics("linespace"), ln, f, "#ffffff")

    def cover(self, g, x0, y0, x1, y1, rid=None, tap=None, badge=None):
        k = self.k
        img = self.image(g["cover"], x1 - x0, y1 - y0, 12 * k) if g.get("cover") else None
        if img:
            self.c.create_image(x0, y0, image=img, anchor="nw")
        else:
            self.placeholder_cover(g, x0, y0, x1, y1)
        T = self.t
        if g["id"] in self.cfg["favorites"]:
            self.text(x1 - 10 * k, y0 + 8 * k, "★", self.font(20 * k, True), T["warn"], anchor="ne")
        if badge:
            f = self.font(11 * k, True)
            bw = f.measure(badge) + 18 * k
            self.rr(x0 + 8 * k, y1 - 34 * k, x0 + 8 * k + bw, y1 - 10 * k, 12 * k, badge_col := T["accent2"])
            self.text(x0 + 8 * k + bw / 2, y1 - 22 * k, badge, f, on_color(badge_col), anchor="center")
        if rid:
            self.region(rid, x0, y0, x1, y1, tap)

    # ------------------------------------------------------------------ main draw
    def redraw(self):
        c = self.c
        W, H = c.winfo_width(), c.winfo_height()
        if W < 50 or H < 50:
            return
        self.W, self.H = W, H
        scale = self.cfg["ui_scale"]
        if self.cfg["tv_auto"] and self.docked:
            scale = max(scale, 130)
        self.k = min(W / 1280, H / 800) * scale / 100
        c.delete("all")
        self.regions = []
        T, k = self.t, self.k
        c.configure(bg=T["bg"])
        self.draw_backdrop(W, H)
        if self.page and self.page[0] == "game":
            self.draw_game_page(self.page[1])
        elif self.page and self.page[0] == "shot":
            self.draw_shot_view(self.page[1])
        elif self.page and self.page[0] == "ram":
            self.draw_ram()
        elif self.page and self.page[0] in ("goal", "remote", "startup", "pad", "backup", "themes", "update"):
            getattr(self, "draw_" + self.page[0])()
        else:
            self.draw_topbar(W)
            y0 = 92 * k
            {"home": self.draw_home, "library": self.draw_library, "play": self.draw_play, "shots": self.draw_shots,
             "storage": self.draw_storage, "system": self.draw_system, "tools": self.draw_tools,
             "settings": self.draw_settings}[self.tab](40 * k, y0, W - 40 * k, H - 54 * k)
            self.draw_hints(W, H)
        if self.focus and not any(r["id"] == self.focus for r in self.regions):
            self.focus = None
        if self.focus_visible:
            if not self.focus:
                self.focus = self.default_focus()
            r = next((r for r in self.regions if r["id"] == self.focus), None)
            if r:
                g = 4 * k
                self.rr(r["x0"] - g, r["y0"] - g, r["x1"] + g, r["y1"] + g, 16 * k, "", outline=T["accent"], width=max(2, 3 * k))
        if self.toast and self.toast[1] > time.time():
            f = self.font(15 * k, True)
            tw = f.measure(self.toast[0]) + 44 * k
            self.rr(W / 2 - tw / 2, H - 108 * k, W / 2 + tw / 2, H - 64 * k, 22 * k, T["text"])
            self.text(W / 2, H - 86 * k, self.toast[0], f, T["bg"], anchor="center")
        if self.entry:
            self.entry.lift()

    def draw_backdrop(self, W, H):
        T, k = self.t, self.k
        key = ("bd", W, H, self.cfg["theme"])
        if key not in self.imgs:
            im = Image.new("RGB", (max(1, W // 4), max(1, H // 4)), tuple(int(T["bg"][i:i + 2], 16) for i in (1, 3, 5)))
            if T.get("grad"):
                im = self.gradient(im.size, T["grad"], T.get("angle", 120))
            d = ImageDraw.Draw(im)
            a = tuple(int(T["accent"][i:i + 2], 16) for i in (1, 3, 5))
            a2 = tuple(int(T["accent2"][i:i + 2], 16) for i in (1, 3, 5))
            w, h = im.size
            glow = 0.08 if T.get("light") else 0.22
            for (cx, cy, rad, col) in ((w * 0.9, h * -0.1, w * 0.55, a), (w * 0.05, h * 0.95, w * 0.45, a2)):
                layer = Image.new("RGB", im.size, (0, 0, 0))
                ImageDraw.Draw(layer).ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=col)
                layer = layer.filter(ImageFilter.GaussianBlur(rad * 0.45))
                im = Image.blend(im, Image.composite(layer, im, layer.convert("L")), glow)
            im = im.resize((W, H), Image.BILINEAR)
            self.imgs[key] = ImageTk.PhotoImage(im)
        self.c.create_image(0, 0, image=self.imgs[key], anchor="nw", tags=("backdrop",))
        self.fx_draw(W, H)

    @staticmethod
    def gradient(size, stops, angle):
        w, h = size
        cols = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in stops]
        a = math.radians(angle)
        dx, dy = math.sin(a), -math.cos(a)
        lo = min(0 * dx + 0 * dy, w * dx, h * dy, w * dx + h * dy)
        hi = max(0 * dx + 0 * dy, w * dx, h * dy, w * dx + h * dy)
        im = Image.new("RGB", size)
        px = im.load()
        n = len(cols) - 1
        for y in range(h):
            for x in range(w):
                f = ((x * dx + y * dy) - lo) / max(1e-6, hi - lo) * n
                i = min(int(f), n - 1) if n else 0
                t = f - i
                a_, b_ = cols[i], cols[min(i + 1, n)]
                px[x, y] = tuple(int(a_[j] + (b_[j] - a_[j]) * t) for j in range(3))
        return im

    def draw_topbar(self, W):
        T, k = self.t, self.k
        c = self.c
        self.rr(40 * k, 24 * k, 84 * k, 68 * k, 14 * k, T["accent"])
        self.text(62 * k, 46 * k, "V", self.font(24 * k, True), on_color(T["accent"]), anchor="center")
        f = self.font(16 * k, True)
        right_room = 230 * k
        pad = 36 * k
        need = sum(f.measure(lab) for _, lab in TABS) + len(TABS) * (pad + 8 * k)
        if 270 * k + need + right_room <= W:
            self.text(98 * k, 46 * k, "VANTA DECK", self.font(17 * k, True), T["text"], anchor="w")
            x = 270 * k
        else:  # big text or a small window: drop the name, then tighten the tabs
            x = 100 * k
            pad = max(14 * k, min(pad, (W - x - right_room - sum(f.measure(lab) for _, lab in TABS)) / len(TABS) - 8 * k))
        for tid, label in TABS:
            w = f.measure(label) + pad
            on = self.tab == tid
            if on:
                self.rr(x, 26 * k, x + w, 66 * k, 20 * k, T["accent"])
            self.text(x + w / 2, 46 * k, label, f, on_color(T["accent"]) if on else T["muted"], anchor="center")
            self.region("tab_" + tid, x, 26 * k, x + w, 66 * k, lambda t_=tid: self.set_tab(t_))
            x += w + 8 * k
        b = self.stats.get("batt")
        right = W - 40 * k
        clock = time.strftime("%H:%M")
        self.text(right, 46 * k, clock, self.font(17 * k, True), T["text"], anchor="e")
        right -= self.font(17 * k, True).measure(clock) + 24 * k
        if b:
            col = T["danger"] if b["pct"] <= 15 and b["status"] != "Charging" else T["good"] if b["status"] in ("Charging", "Full") else T["text"]
            lab = f"{'⚡ ' if b['status'] == 'Charging' else ''}{b['pct']}%"
            self.text(right, 46 * k, lab, self.font(16 * k, True), col, anchor="e")
            bw = 34 * k
            x1 = right - self.font(16 * k, True).measure(lab) - 10 * k
            self.rr(x1 - bw, 37 * k, x1, 55 * k, 4 * k, "", outline=T["muted"], width=max(1, 1.5 * k))
            self.rr(x1 - bw + 3 * k, 40 * k, x1 - bw + 3 * k + (bw - 6 * k) * b["pct"] / 100, 52 * k, 2 * k, col)

    def draw_hints(self, W, H):
        T, k = self.t, self.k
        hints = [("A", "Select"), ("B", "Back"), ("L1 R1", "Switch tab")]
        if self.tab in ("home", "library"):
            hints.insert(1, ("X", "Play"))
        if self.tab == "library":
            hints.insert(2, ("Y", "Favorite"))
        f, fb = self.font(13 * k), self.font(12 * k, True)
        x = W - 40 * k
        for key, lab in reversed(hints):
            self.text(x, H - 26 * k, lab, f, T["muted"], anchor="e")
            x -= f.measure(lab) + 8 * k
            w = fb.measure(key) + 14 * k
            self.rr(x - w, H - 38 * k, x, H - 14 * k, 12 * k, T["panel2"])
            self.text(x - w / 2, H - 26 * k, key, fb, T["text"], anchor="center")
            x -= w + 20 * k
        g = None
        if self.running:
            g = next((x for x in self.library or [] if x["appid"] in self.running), None)
            if g:
                s = self.running[g["appid"]]
                self.text(40 * k, H - 26 * k, f"● Playing {g['name']}  ·  {dc.fmt_duration(time.time() - s)}", self.font(14 * k, True),
                          T["good"], anchor="w")
        extra = [lab for on, lab in ((self.cfg["guest"], "GUEST MODE"), (bool(self.cfg["paused"]), f"{len(self.cfg['paused'])} APP{'S' if len(self.cfg['paused']) != 1 else ''} FROZEN"),
                                     (bool(self.cfg["batt_goal"]), "GOAL " + time.strftime("%H:%M", time.localtime(self.cfg["batt_goal"] or 0))),
                                     (bool(self.update and self.update["newer"]), "UPDATE READY"))
                 if on]
        if extra:
            ex = 40 * k + (self.font(14 * k, True).measure("● Playing " + (g["name"] if self.running and g else "")) + 140 * k
                           if self.running and g else 0)
            for lab in extra:
                w = fb.measure(lab) + 20 * k
                self.rr(ex, H - 38 * k, ex + w, H - 14 * k, 12 * k, mix(T["panel2"], T["warn"], 0.35))
                self.text(ex + w / 2, H - 26 * k, lab, fb, T["text"], anchor="center")
                ex += w + 8 * k

    def card(self, x0, y0, x1, y1, title=None):
        T, k = self.t, self.k
        self.rr(x0, y0, x1, y1, 18 * k, mix(T["panel"], T["bg"], 0.1))
        if title:
            self.text(x0 + 20 * k, y0 + 18 * k, title, self.font(12.5 * k, True), T["muted"])
        return y0 + (46 if title else 18) * k

    # ------------------------------------------------------------------ Home
    def draw_home(self, x0, y0, x1, y1):
        T, k, c = self.t, self.k, self.c
        if self.library is None:
            self.text((x0 + x1) / 2, (y0 + y1) / 2, "Reading your Steam library…", self.font(20 * k), T["muted"], anchor="center")
            return
        if not self.library:
            self.empty_library(x0, y0, x1, y1)
            return
        g = self.home_game()
        hh = (y1 - y0) * 0.56
        # hero
        self.rr(x0, y0, x1, y0 + hh, 22 * k, T["panel"])
        if g and g.get("hero"):
            img = self.hero_image(g["hero"], x1 - x0, hh)
            if img:
                c.create_image(x0, y0, image=img, anchor="nw")
        if g:
            cw = hh * 0.62
            cy0 = y0 + 22 * k
            self.cover(g, x0 + 26 * k, cy0, x0 + 26 * k + cw * 0.92, cy0 + (hh - 44 * k))
            tx = x0 + 26 * k + cw + 10 * k
            st = "PLAYING NOW" if g["appid"] in self.running else ("UP NEXT" if g["id"] in self.cfg["queue"][:1] and not g["last"]
                                                                   else "JUMP BACK IN")
            self.text(tx, y0 + hh - 176 * k, st, self.font(13 * k, True), T["accent"])
            self.text(tx + 2 * k, y0 + hh - 150 * k, g["name"], self.font(36 * k, True), "#000000", maxw=x1 - tx - 30 * k)
            self.text(tx, y0 + hh - 152 * k, g["name"], self.font(36 * k, True), T["text"], maxw=x1 - tx - 30 * k)
            bits = []
            if g["minutes"]:
                bits.append(f"{dc.fmt_duration(g['minutes'] * 60)} played")
            if g["last"]:
                bits.append(f"last played {dc.ago(g['last'])}")
            if g["size"]:
                bits.append(dc.fmt_bytes(g["size"]))
            bits.append(g["source"])
            self.text(tx, y0 + hh - 100 * k, "  ·  ".join(bits), self.font(15 * k), T["muted"], maxw=x1 - tx - 30 * k)
            note = (self.cfg["notes"].get(g["id"]) or {}).get("text") if not self.cfg["guest"] else None
            if note:
                self.text(tx, y0 + hh - 76 * k, "✎ " + note, self.font(14 * k, True), mix(T["text"], T["accent"], 0.4),
                          maxw=x1 - tx - 30 * k)
            by = y0 + hh - 64 * k
            if note:
                by += 4 * k
            self.button("home_play", tx, by, tx + 200 * k, by + 46 * k, "▶  PLAY" if g["appid"] not in self.running else "● RUNNING",
                        lambda: self.play(g), "accent", 17)
            self.button("home_page", tx + 214 * k, by, tx + 400 * k, by + 46 * k, "GAME PAGE", lambda: self.open_game(g["id"]))
        # row
        ry = y0 + hh + 22 * k
        self.text(x0 + 4 * k, ry, "RECENT", self.font(13 * k, True), T["muted"])
        ry += 26 * k
        th = (y1 - ry) - 8 * k
        tw = th * 2 / 3
        lib = self.recent()
        n = max(1, int((x1 - x0 + 14 * k) // (tw + 14 * k)) - 1)
        x = x0
        for gg in lib[:n]:
            sel = g and gg["id"] == g["id"]
            self.cover(gg, x, ry, x + tw, ry + th, "home_g_" + gg["id"], lambda gid=gg["id"]: self.pick_home(gid),
                       badge="PLAYING" if gg["appid"] in self.running else None)
            if sel:
                self.rr(x + tw * 0.32, ry + th + 3 * k, x + tw * 0.68, ry + th + 8 * k, 3 * k, T["accent"])
            x += tw + 14 * k
        # side tile: today / streak / queue
        self.rr(x, ry, x1, ry + th, 18 * k, mix(T["panel"], T["bg"], 0.1))
        ix = x + 18 * k
        iy = ry + 16 * k
        f, fb = self.font(13 * k), self.font(22 * k, True)
        for lab, val in (("TODAY", dc.fmt_duration(self.played_today())), ("THIS WEEK", dc.fmt_duration(self.played_since(self.week_start()))),
                         ("STREAK", f"{self.streak()} day{'s' if self.streak() != 1 else ''}")):
            self.text(ix, iy, lab, self.font(12 * k, True), T["muted"])
            self.text(ix, iy + 18 * k, val, fb, T["text"])
            iy += (th - 32 * k) / 3
        self.region("home_lib", x, ry, x1, ry + th, lambda: self.set_tab("play"))

    def pick_home(self, gid):
        if self.cfg["home_sel"] == gid:
            self.open_game(gid)
            return
        self.cfg["home_sel"] = gid
        self.redraw()

    def empty_library(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        msg = "No Steam games found" if dc.steam_root() else "Steam isn't set up on this account yet"
        self.text((x0 + x1) / 2, (y0 + y1) / 2 - 20 * k, msg, self.font(24 * k, True), T["text"], anchor="center")
        self.text((x0 + x1) / 2, (y0 + y1) / 2 + 16 * k, "Install a game in Steam and it shows up here.", self.font(16 * k), T["muted"],
                  anchor="center")

    # ------------------------------------------------------------------ Library
    FILTERS = [("all", "All"), ("steam", "Steam"), ("nonsteam", "Other stores"), ("fav", "★ Favorites"), ("queue", "Up next"),
               ("finished", "Finished")]
    SORTS = [("recent", "Recent"), ("az", "A–Z"), ("played", "Most played"), ("rating", "Your rating"), ("size", "Size")]

    def lib_games(self):
        f = self.cfg["lib_filter"]
        lib = list(self.library or [])
        if f == "steam":
            lib = [g for g in lib if g["source"] == "Steam"]
        elif f == "nonsteam":
            lib = [g for g in lib if g["source"] != "Steam"]
        elif f == "fav":
            lib = [g for g in lib if g["id"] in self.cfg["favorites"]]
        elif f == "queue":
            order = {gid: i for i, gid in enumerate(self.cfg["queue"])}
            return sorted([g for g in lib if g["id"] in order], key=lambda g: order[g["id"]])
        elif f == "finished":
            lib = [g for g in lib if g["id"] in self.cfg["finished"]]
        if self.search:
            q = self.search.lower()
            lib = [g for g in lib if q in g["name"].lower()]
        s = self.cfg["lib_sort"]
        rt = self.cfg["ratings"]
        key = {"recent": lambda g: (-g["last"], g["name"].lower()), "az": lambda g: g["name"].lower(),
               "played": lambda g: -g["minutes"], "size": lambda g: -g["size"],
               "rating": lambda g: (-rt.get(g["id"], 0), g["name"].lower())}.get(s, lambda g: g["name"].lower())
        lib.sort(key=key)
        return lib

    def draw_library(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        if self.library is None:
            self.text((x0 + x1) / 2, (y0 + y1) / 2, "Reading your Steam library…", self.font(20 * k), T["muted"], anchor="center")
            return
        x = x0
        f = self.font(14 * k, True)
        for fid, lab in self.FILTERS:
            w = f.measure(lab) + 30 * k
            on = self.cfg["lib_filter"] == fid
            self.rr(x, y0, x + w, y0 + 38 * k, 19 * k, T["accent"] if on else T["panel2"])
            self.text(x + w / 2, y0 + 19 * k, lab, f, on_color(T["accent"]) if on else T["text"], anchor="center")
            self.region("lf_" + fid, x, y0, x + w, y0 + 38 * k, lambda v=fid: self.set_cfg("lib_filter", v, scroll="lib"))
            x += w + 8 * k
        x += 10 * k
        for rid, lab, fn, on in (("lib_search", f"“{self.search}”  ✕" if self.search else "Search", self.search_tap, bool(self.search)),
                                 ("lib_dice", "Surprise me", self.surprise, False)):
            w = f.measure(lab) + 30 * k
            self.rr(x, y0, x + w, y0 + 38 * k, 19 * k, T["accent2"] if on else mix(T["panel2"], T["accent2"], 0.18))
            self.text(x + w / 2, y0 + 19 * k, lab, f, on_color(T["accent2"]) if on else T["text"], anchor="center", maxw=w - 16 * k)
            self.region(rid, x, y0, x + w, y0 + 38 * k, fn)
            x += w + 8 * k
        sl = dict(self.SORTS)[self.cfg["lib_sort"]]
        lab = "Sort: " + sl + "  ›"
        w = f.measure(lab) + 30 * k
        self.rr(x1 - w, y0, x1, y0 + 38 * k, 19 * k, T["panel2"])
        self.text(x1 - w / 2, y0 + 19 * k, lab, f, T["text"], anchor="center")
        ids = [s for s, _ in self.SORTS]
        self.region("lib_sort", x1 - w, y0, x1, y0 + 38 * k,
                    lambda: self.set_cfg("lib_sort", ids[(ids.index(self.cfg["lib_sort"]) + 1) % len(ids)], scroll="lib"))
        games = self.lib_games()
        gy = y0 + 54 * k
        if not games:
            self.text((x0 + x1) / 2, (gy + y1) / 2, f"No games match “{self.search}”" if self.search else "Nothing here yet",
                      self.font(18 * k), T["muted"], anchor="center")
            return
        cols = 6
        gap = 16 * k
        tw = (x1 - x0 - gap * (cols - 1)) / cols
        th = tw * 1.5
        rows = math.ceil(len(games) / cols)
        total = rows * (th + gap + 26 * k)
        off = self.clamp_scroll("lib", total - (y1 - gy))
        self.c.create_rectangle(0, 0, 0, 0)  # (keeps item order simple)
        for i, g in enumerate(games):
            r_, cn = divmod(i, cols)
            gx = x0 + cn * (tw + gap)
            ty = gy + r_ * (th + gap + 26 * k) - off
            if ty < gy - 2 or ty > y1:
                continue  # rows scroll out under the filters instead of drawing over them
            badge = "PLAYING" if g["appid"] in self.running else ("UPDATING" if g.get("updating") else
                                                                   ("✓ FINISHED" if g["id"] in self.cfg["finished"] else None))
            self.cover(g, gx, ty, gx + tw, ty + th, "g_" + g["id"], lambda gid=g["id"]: self.open_game(gid), badge=badge)
            sub = dc.fmt_duration(g["minutes"] * 60) if g["minutes"] else (g["source"] if g["source"] != "Steam" else "Not played")
            if self.cfg["ratings"].get(g["id"]):
                sub = "★" * self.cfg["ratings"][g["id"]] + "  " + sub
            self.text(gx + 2 * k, ty + th + 6 * k, sub, self.font(12.5 * k), T["muted"], maxw=tw)
        self.region("lib_scroll", x0, gy, x1, y1, None, scroll="lib")

    def mask_top(self, y):
        """Hide tiles that scrolled up under the filters (redraw the filters' strip on top)."""
        T = self.t
        items = self.c.find_overlapping(0, 0, self.W, y)
        bd = self.c.find_withtag("backdrop")
        for it in items:
            if it in bd:
                continue
            x0_, y0_, x1_, y1_ = self.c.bbox(it) or (0, 0, 0, 0)
            if y0_ > 80 * self.k and y1_ > y:  # a scrolled tile crossing the line
                self.c.delete(it)

    def clamp_scroll(self, key, max_off):
        off = max(0, min(self.scroll.get(key, 0), max(0, max_off)))
        self.scroll[key] = off
        return off

    def wheel(self, d):
        key = ({"library": "lib", "storage": "storage", "settings": "settings", "play": "play", "shots": "shots"}.get(self.tab)
               if not self.page else {"game": "game", "ram": "ram", "themes": "themes"}.get(self.page[0]))
        if key:
            self.scroll[key] = self.scroll.get(key, 0) + d * 120 * self.k
            self.redraw()

    def set_cfg(self, key, v, scroll=None):
        self.cfg[key] = v
        if scroll:
            self.scroll[scroll] = 0
        self.redraw()

    # ------------------------------------------------------------------ Game page
    def open_game(self, gid):
        g = self.game(gid)
        if not g:
            return
        self.page = ("game", gid)
        self.scroll["game"] = 0
        self.focus = "gp_play" if self.focus_visible else None
        self.fetch_info(g)
        self.redraw()

    def close_page(self):
        if self.page and self.page[0] == "ram":
            self.ram = None
        self.page = None
        self.hide_entry()
        self.focus = None
        self.redraw()

    def play(self, g):
        if g["appid"] in self.running:
            self.show_toast(f"{g['name']} is already running")
            return
        if (dc.launch(g["launch"]) if g["launch"].startswith("steam://") else dc.open_url(g["launch"])):
            self.show_toast(f"Starting {g['name']}…")
            self.cfg["home_sel"] = g["id"]
        else:
            self.show_toast("Couldn't reach Steam")

    def toggle(self, key, gid):
        lst = list(self.cfg[key])
        lst.remove(gid) if gid in lst else lst.append(gid)
        self.cfg[key] = lst
        self.redraw()

    def set_finished(self, g, on):
        fin = dict(self.cfg["finished"])
        if on:
            fin[g["id"]] = {"t": time.time(), "name": g["name"]}
            self.cfg["queue"] = [x for x in self.cfg["queue"] if x != g["id"]]
            self.show_toast(f"Finished {g['name']}!")
        else:
            fin.pop(g["id"], None)
        self.cfg["finished"] = fin
        self.redraw()

    def draw_game_page(self, gid):
        g = self.game(gid)
        T, k, c = self.t, self.k, self.c
        W, H = self.W, self.H
        if not g:
            self.page = None
            return self.redraw()
        hh = H * 0.42
        if g.get("hero"):
            img = self.hero_image(g["hero"], W, hh)
            if img:
                c.create_image(0, 0, image=img, anchor="nw")
        self.button("gp_back", 32 * k, 26 * k, 140 * k, 68 * k, "‹  BACK", self.close_page, "ghost")
        cw, chh = 210 * k, 315 * k
        cx0, cy0 = 48 * k, hh - chh * 0.62
        self.cover(g, cx0, cy0, cx0 + cw, cy0 + chh)
        tx = cx0 + cw + 30 * k
        self.text(tx, hh - 14 * k, g["name"], self.font(34 * k, True), T["text"], anchor="sw", maxw=W - tx - 40 * k)
        bits = [g["source"]]
        if g["minutes"]:
            bits.append(f"{dc.fmt_duration(g['minutes'] * 60)} played")
        bits.append(f"last played {dc.ago(g['last'])}")
        if g["size"]:
            bits.append(dc.fmt_bytes(g["size"]))
        self.text(tx, hh + 6 * k, "  ·  ".join(bits), self.font(15 * k), T["muted"], maxw=W - tx - 40 * k)
        by = hh + 42 * k
        running = g["appid"] in self.running
        acts = [("gp_play", "● RUNNING" if running else "▶  PLAY", lambda: self.play(g), "accent", 200),
                ("gp_fav", "★ FAVORITE" if g["id"] in self.cfg["favorites"] else "☆ FAVORITE",
                 lambda: self.toggle("favorites", g["id"]), "normal", 160),
                ("gp_queue", "IN UP NEXT ✓" if g["id"] in self.cfg["queue"] else "+ UP NEXT", lambda: self.toggle("queue", g["id"]),
                 "normal", 160),
                ("gp_fin", "FINISHED ✓" if g["id"] in self.cfg["finished"] else "MARK FINISHED",
                 lambda: self.set_finished(g, g["id"] not in self.cfg["finished"]), "normal", 170)]
        if g["source"] == "Steam":
            acts.append(("gp_store", "STEAM PAGE", lambda: dc.launch(f"steam://nav/games/details/{g['appid']}"), "normal", 150))
        x = tx
        for rid, lab, fn, st, w in acts:
            self.button(rid, x, by, x + w * k, by + 46 * k, lab, fn, st)
            x += w * k + 10 * k
        # info cards (scrolling area)
        top = by + 66 * k
        off = self.scroll.get("game", 0)
        cards = self.game_cards(g)
        colw = (W - 96 * k - 20 * k) / 2
        ys = [top - off, top - off]
        for card in cards:
            col = 0 if ys[0] <= ys[1] else 1
            cx = 48 * k + col * (colw + 20 * k)
            h = self.card_height(card, colw)
            if ys[col] >= top - 2 and ys[col] < H:
                self.draw_card(card, cx, ys[col], cx + colw, ys[col] + h)
            ys[col] += h + 16 * k
        total = max(ys) + off - top
        self.clamp_scroll("game", total - (H - top - 30 * k))
        self.region("game_scroll", 48 * k, top, W - 48 * k, H, None, scroll="game")

    def game_cards(self, g):
        T = self.t
        info = self.data.get(g["id"]) or {}
        cards = []
        if g["source"] == "Steam":
            lines = []
            deck = info.get("deck")
            if "deck" not in info:
                lines.append(("Asking Steam…", "muted"))
            elif deck:
                lines.append((f"Steam Deck: {deck[0]}", deck[1]))
            pt = info.get("proton")
            if pt and pt[0]:
                lines.append((f"ProtonDB: {pt[0].title()}  ·  {pt[1]} reports", "good" if pt[0] in ("platinum", "gold", "native") else "text"))
            rv = info.get("reviews")
            if rv and rv.get("pct") is not None:
                lines.append((f"Steam reviews: {rv['desc']}  ·  {rv['pct']}% of {rv['total']:,}", "text"))
            cards.append({"title": "HOW IT RUNS", "lines": lines or [("No ratings yet", "muted")],
                          "buttons": [("PROTONDB", lambda: dc.open_url(f"https://www.protondb.com/app/{g['appid']}"))]})
        note = (self.cfg["notes"].get(g["id"]) or {}).get("text")
        guest = self.cfg["guest"]
        if not guest:
            cards.append({"title": "✎ NOTE", "lines": [(note, "text")] if note else [("Where you left off, a boss to beat, settings that "
                                                                                 "worked… Shown on Home.", "muted")],
                          "buttons": [("EDIT NOTE" if note else "WRITE A NOTE", lambda: self.edit_note(g))] +
                                     ([("CLEAR", lambda: self.save_note(g, ""))] if note else [])})
        r = self.cfg["ratings"].get(g["id"], 0)
        cards.append({"title": "YOUR RATING", "lines": [("★" * r + "☆" * (5 - r) + f"   {r} of 5  ·  tap the same stars to clear", "warn")]
                      if r else [("How good is it? The library can sort by your rating.", "muted")],
                      "buttons": [("★" * n, lambda n_=n: self.rate(g, n_)) for n in range(1, 6)]})
        pw = self.cfg["power"].get(g["appid"])
        b = self.stats.get("batt") or {}
        if pw and pw[1] >= 60:
            avg = pw[0] / pw[1]
            lines = [(f"Draws about {avg:.1f} W while you play on battery", "text")]
            if b.get("full_wh"):
                lines.append((f"A full charge lasts about {dc.fmt_duration(b['full_wh'] / avg * 3600)}", "good"))
            if b.get("status") == "Discharging" and b.get("pct") and b.get("full_wh"):
                lines.append((f"From {b['pct']}% now: about {dc.fmt_duration(b['full_wh'] * b['pct'] / 100 / avg * 3600)}", "muted"))
            cards.append({"title": "BATTERY LIFE", "lines": lines, "buttons": []})
        shots = [x for x in self.shots or [] if x["appid"] == g["appid"]]
        if shots:
            cards.append({"title": "SCREENSHOTS", "lines": [(f"{len(shots)} screenshot{'s' if len(shots) != 1 else ''}  ·  "
                                                             f"latest {dc.ago(shots[0]['t'])}", "text")],
                          "buttons": [("VIEW", lambda: self.show_game_shots(g))]})
        ss = [x for x in self.cfg["sessions"] if x["appid"] == g["appid"]] if not guest else []
        if ss:
            tot = sum(x["dur"] for x in ss)
            lines = [(f"{len(ss)} sessions tracked  ·  {dc.fmt_duration(tot)}  ·  about {dc.fmt_duration(tot / len(ss))} each", "text")]
            lines += [(f"{time.strftime('%b %d, %H:%M', time.localtime(x['start']))}  ·  {dc.fmt_duration(x['dur'])}", "muted") for x in ss[:5]]
            cards.append({"title": "YOUR SESSIONS", "lines": lines, "buttons": []})
        news = info.get("news")
        if news:
            n = news[0]
            cards.append({"title": "LATEST NEWS" + ("  ·  PATCH" if n["patch"] else ""),
                          "lines": [(n["title"], "text"), (time.strftime("%b %d", time.localtime(n["date"])) + "  ·  " + n["text"][:170], "muted")],
                          "buttons": [("READ", lambda: dc.open_url(n["url"]))] if n["url"] else []})
        if g["source"] == "Steam":
            tool = (f"Runs with {g['tool']} (set for this game)" if g.get("tool") else
                    f"Runs with Steam's default{': ' + g['tool_default'] if g.get('tool_default') else ''}")
            cards.append({"title": "MANAGE", "lines": [(tool, "text"),
                                                       (f"Launch options: {g['opts']}" if g.get("opts") else "No launch options", "muted"),
                                                       (f"Installed in {g['lib']}", "muted")],
                          "buttons": [("PROPERTIES", lambda: dc.launch(f"steam://gameproperties/{g['appid']}")),
                                      ("UNINSTALL" if not self.is_armed("un_" + g["id"]) else "TAP AGAIN",
                                       lambda: self.confirm("un_" + g["id"], lambda: dc.launch(f"steam://uninstall/{g['appid']}"),
                                                            "Tap again: Steam will ask to uninstall"))]})
        return cards

    def card_height(self, card, w):
        k = self.k
        f = self.font(15 * k)
        n = sum(max(1, len(self.wrap(t, f, w - 40 * k))) for t, _ in card["lines"])
        return 50 * k + n * f.metrics("linespace") + (62 * k if card["buttons"] else 14 * k)

    def draw_card(self, card, x0, y0, x1, y1):
        T, k = self.t, self.k
        self.rr(x0, y0, x1, y1, 18 * k, mix(T["panel"], T["bg"], 0.1), tags=("card",))
        self.text(x0 + 20 * k, y0 + 18 * k, card["title"], self.font(12.5 * k, True), T["muted"], tags=("card",))
        f = self.font(15 * k)
        y = y0 + 44 * k
        for t, col in card["lines"]:
            for ln in self.wrap(t, f, x1 - x0 - 40 * k) or [""]:
                self.text(x0 + 20 * k, y, ln, f, T.get(col, T["text"]), tags=("card",))
                y += f.metrics("linespace")
        x = x0 + 20 * k
        bf = self.font(13.5 * k, True)
        for i, (lab, fn) in enumerate(card["buttons"]):
            w = bf.measure(lab) + 34 * k
            self.button(f"cb_{card['title']}_{i}", x, y1 - 54 * k, x + w, y1 - 16 * k, lab, fn, "normal", 13.5)
            x += w + 10 * k

    def rate(self, g, n):
        rt = dict(self.cfg["ratings"])
        if rt.get(g["id"]) == n:
            rt.pop(g["id"])
            self.show_toast("Rating cleared")
        else:
            rt[g["id"]] = n
            self.show_toast(f"{g['name']}: {'★' * n}")
        self.cfg["ratings"] = rt

    def search_tap(self):
        if self.search:
            self.search = ""
            self.scroll["lib"] = 0
            self.redraw()
        else:
            self.ask_text("", self.set_search, "Type part of a name (Steam + X opens the keyboard), then Enter")

    def set_search(self, text):
        self.search = (text or "").strip()[:40]
        self.scroll["lib"] = 0
        self.hide_entry()
        self.redraw()

    def surprise(self):
        lib = [g for g in self.library or [] if g["appid"] not in self.running]
        if not lib:
            return
        fin = self.cfg["finished"]
        pool = [g for g in lib if g["id"] in self.cfg["queue"] or (g["minutes"] < 120 and g["id"] not in fin)] or lib
        g = random.choice(pool)
        self.open_game(g["id"])
        self.show_toast(f"How about {g['name']}?")

    def ask_text(self, value, on_save, hint):
        self.hide_entry()
        k, T = self.k, self.t
        var = tk.StringVar(value=value)
        e = tk.Entry(self.root, textvariable=var, font=self.font(18 * k), bg=T["panel2"], fg=T["text"], insertbackground=T["text"],
                     relief="flat", highlightthickness=2, highlightcolor=T["accent"])
        e.place(x=60 * k, y=self.H - 140 * k, width=self.W - 260 * k, height=56 * k)
        ok = tk.Button(self.root, text="OK", font=self.font(15 * k, True), bg=T["accent"], fg=on_color(T["accent"]), relief="flat",
                       command=lambda: on_save(var.get()))
        ok.place(x=self.W - 190 * k, y=self.H - 140 * k, width=130 * k, height=56 * k)
        e.bind("<Return>", lambda ev: on_save(var.get()))
        e.bind("<Escape>", lambda ev: self.hide_entry())
        e.focus_set()
        self.entry = e
        self.entry_btn = ok
        self.show_toast(hint)

    # ------------------------------------------------------------------ notes (a real text box: the Steam keyboard works with it)
    def edit_note(self, g):
        self.hide_entry()
        k, T = self.k, self.t
        var = tk.StringVar(value=(self.cfg["notes"].get(g["id"]) or {}).get("text", ""))
        e = tk.Entry(self.root, textvariable=var, font=self.font(18 * k), bg=T["panel2"], fg=T["text"], insertbackground=T["text"],
                     relief="flat", highlightthickness=2, highlightcolor=T["accent"])
        e.place(x=60 * k, y=self.H - 140 * k, width=self.W - 260 * k, height=56 * k)
        ok = tk.Button(self.root, text="SAVE", font=self.font(15 * k, True), bg=T["accent"], fg=on_color(T["accent"]), relief="flat",
                       command=lambda: self.save_note(g, var.get()))
        ok.place(x=self.W - 190 * k, y=self.H - 140 * k, width=130 * k, height=56 * k)
        e.bind("<Return>", lambda ev: self.save_note(g, var.get()))
        e.bind("<Escape>", lambda ev: self.hide_entry())
        e.focus_set()
        self.entry = e
        self.entry_btn = ok
        self.show_toast("Type your note (Steam + X opens the keyboard), then Enter")

    def hide_entry(self):
        if self.entry:
            self.entry.destroy()
            self.entry_btn.destroy()
            self.entry = None
            self.c.focus_set()

    def save_note(self, g, text):
        notes = dict(self.cfg["notes"])
        text = (text or "").strip()[:240]
        if text:
            notes[g["id"]] = {"text": text, "t": time.time()}
        else:
            notes.pop(g["id"], None)
        self.cfg["notes"] = notes
        self.hide_entry()
        self.show_toast("Note saved" if text else "Note cleared")

    # ------------------------------------------------------------------ Play: calendar, totals, top games, badges
    def day_minutes(self):
        days = {}
        for x in self.cfg["sessions"]:
            t, end = x["start"], x["start"] + x["dur"]
            while t < end:  # split sessions that cross midnight
                lt = time.localtime(t)
                nxt = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + 1, 0, 0, 0, 0, 0, -1))
                key = time.strftime("%Y-%m-%d", lt)
                days[key] = days.get(key, 0) + (min(end, nxt) - t) / 60
                t = nxt
        for aid, st in self.running.items():
            key = time.strftime("%Y-%m-%d")
            days[key] = days.get(key, 0) + (time.time() - max(st, time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1)))) / 60
        return days

    def best_streak(self):
        import datetime as dt
        days = sorted({time.strftime("%Y-%m-%d", time.localtime(x["start"])) for x in self.cfg["sessions"]})
        best = run = 0
        prev = None
        for d in days:
            cur = dt.date.fromisoformat(d)
            run = run + 1 if prev and (cur - prev).days == 1 else 1
            best = max(best, run)
            prev = cur
        return max(best, self.streak())

    def badges(self):
        ss = self.cfg["sessions"]
        steam_hours = sum(g["minutes"] for g in self.library or []) / 60
        prog = {"first": (len(ss), 1), "marathon": (max([x["dur"] for x in ss] or [0]) / 3600, 3),
                "owl": (sum(1 for x in ss if time.localtime(x["start"]).tm_hour < 5), 1),
                "streak7": (self.best_streak(), 7), "explorer": (len({x["appid"] for x in ss}), 10),
                "finisher": (len(self.cfg["finished"]), 3), "critic": (len(self.cfg["ratings"]), 5),
                "century": (steam_hours, 100)}
        return [(bid, name, desc, min(prog[bid][0], prog[bid][1]), prog[bid][1]) for bid, name, desc in BADGES]

    def top_games(self, since):
        tot = {}
        for x in self.cfg["sessions"]:
            if x["start"] + x["dur"] > since:
                tot[x["appid"]] = tot.get(x["appid"], 0) + x["start"] + x["dur"] - max(x["start"], since)
        for aid, st in self.running.items():
            tot[aid] = tot.get(aid, 0) + time.time() - max(st, since)
        names = {x["appid"]: x["name"] for x in self.cfg["sessions"]}
        out = []
        for aid, sec in sorted(tot.items(), key=lambda kv: -kv[1]):
            g = self.game_by_appid(aid)
            out.append((g["name"] if g else names.get(aid, f"App {aid}"), sec, g))
        return out

    def draw_play(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        if self.cfg["guest"]:
            self.text((x0 + x1) / 2, (y0 + y1) / 2 - 20 * k, "Guest mode is on", self.font(26 * k, True), T["text"], anchor="center")
            self.text((x0 + x1) / 2, (y0 + y1) / 2 + 20 * k, "Your play stats are hidden and nothing new is tracked. Turn it off in Tools.",
                      self.font(16 * k), T["muted"], anchor="center")
            return
        off = self.scroll.get("play", 0)
        top = y0
        y0 = y0 - off
        ss = self.cfg["sessions"]

        def vis(a, b):
            return a >= top - 2 and b <= y1 + 2
        lw = (x1 - x0) * 0.58
        rx = x0 + lw + 20 * k
        # totals
        tiles = [("THIS WEEK", dc.fmt_duration(self.played_since(self.week_start()))),
                 ("THIS MONTH", dc.fmt_duration(self.played_since(self.month_start()))),
                 ("SESSIONS", str(len(ss))),
                 ("LONGEST", dc.fmt_duration(max([x["dur"] for x in ss] or [0])))]
        tw = (lw - 3 * 14 * k) / 4
        for i, (lab, val) in enumerate(tiles if vis(y0, y0 + 92 * k) else []):
            tx = x0 + i * (tw + 14 * k)
            self.rr(tx, y0, tx + tw, y0 + 92 * k, 18 * k, mix(T["panel"], T["bg"], 0.1))
            self.text(tx + 18 * k, y0 + 16 * k, lab, self.font(12 * k, True), T["muted"])
            self.text(tx + 18 * k, y0 + 40 * k, val, self.font(26 * k, True), T["text"], maxw=tw - 30 * k)
        # calendar
        cy = y0 + 110 * k
        weeks = 20
        ch = 32 * k
        cell = min((lw - 40 * k - 40 * k) / weeks, ch) - 5 * k
        hh = 46 * k + 7 * (cell + 5 * k) + 44 * k
        cal = vis(cy, cy + hh)
        self.rr(x0, cy, x0 + lw, cy + hh, 18 * k, mix(T["panel"], T["bg"], 0.1)) if cal else None
        self.text(x0 + 20 * k, cy + 18 * k, f"YOUR LAST {weeks} WEEKS", self.font(12.5 * k, True), T["muted"])
        days = self.day_minutes() if cal else {}
        import datetime as dt
        today = dt.date.today()
        start = today - dt.timedelta(days=today.weekday() + 7 * (weeks - 1))
        gx0 = x0 + 52 * k
        gy0 = cy + 46 * k
        f = self.font(11 * k)
        for r_, lab in ((0, "Mon"), (2, "Wed"), (4, "Fri"), (6, "Sun")) if cal else ():
            self.text(x0 + 18 * k, gy0 + r_ * (cell + 5 * k) + cell / 2, lab, f, T["muted"], anchor="w")
        last_month = None
        for w in range(weeks if cal else 0):
            for d in range(7):
                day = start + dt.timedelta(days=w * 7 + d)
                if day > today:
                    continue
                m = days.get(day.isoformat(), 0)
                lvl = 0 if m < 1 else 1 if m < 30 else 2 if m < 90 else 3 if m < 180 else 4
                col = mix(T["panel2"], T["accent"], (0, 0.3, 0.55, 0.8, 1)[lvl])
                cx_ = gx0 + w * (cell + 5 * k)
                cy_ = gy0 + d * (cell + 5 * k)
                self.rr(cx_, cy_, cx_ + cell, cy_ + cell, 4 * k, col)
            mday = start + dt.timedelta(days=w * 7)
            if mday.month != last_month:
                last_month = mday.month
                self.text(gx0 + w * (cell + 5 * k), gy0 + 7 * (cell + 5 * k) + 4 * k, mday.strftime("%b"), f, T["muted"])
        lx = x0 + lw - 20 * k
        for lvl in range(4, -1, -1) if cal else ():
            self.rr(lx - cell * 0.6, cy + 16 * k, lx, cy + 16 * k + cell * 0.6, 3 * k,
                    mix(T["panel2"], T["accent"], (0, 0.3, 0.55, 0.8, 1)[lvl]))
            lx -= cell * 0.6 + 4 * k
        if cal:
            self.text(lx - 4 * k, cy + 16 * k + cell * 0.3, "less → more", f, T["muted"], anchor="e")
        # monthly wrap
        wy = cy + hh + 16 * k
        ms = self.month_start()
        mt = [x for x in ss if x["start"] >= ms]
        tg = self.top_games(ms)
        wd = {}
        hrs = {}
        for x in mt:
            lt = time.localtime(x["start"])
            wd[lt.tm_wday] = wd.get(lt.tm_wday, 0) + x["dur"]
            hrs[lt.tm_hour // 3] = hrs.get(lt.tm_hour // 3, 0) + x["dur"]
        lines = []
        if mt:
            nd = len({time.strftime("%d", time.localtime(x["start"])) for x in mt})
            lines.append((f"{dc.fmt_duration(sum(x['dur'] for x in mt))} over {nd} day{'s' if nd != 1 else ''}, "
                          f"{len({x['appid'] for x in mt})} game{'s' if len({x['appid'] for x in mt}) != 1 else ''}", "text"))
            if tg:
                lines.append((f"Most played: {tg[0][0]} ({dc.fmt_duration(tg[0][1])})", "text"))
            days_n = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]
            slot = ["at night", "early mornings", "in the morning", "around midday", "in the afternoon", "early evenings",
                    "in the evening", "late evenings"]
            lines.append((f"You play most on {days_n[max(wd, key=wd.get)]}, {slot[max(hrs, key=hrs.get)]}", "muted"))
        else:
            lines.append(("Nothing tracked this month yet. Vanta counts your sessions while it stays open in the background.", "muted"))
        card = {"title": time.strftime("%B").upper() + " SO FAR", "lines": lines, "buttons": []}
        h = self.card_height(card, lw)
        if vis(wy, wy + h):
            self.draw_card(card, x0, wy, x0 + lw, wy + h)
        left_end = wy + h
        # top games (right)
        ry = y0
        rng = self.cfg["play_range"]
        since = {"week": self.week_start(), "month": self.month_start(), "all": 0}.get(rng, self.month_start())
        games = self.top_games(since)[:5]
        th_ = 112 * k + 5 * 44 * k
        if vis(ry, ry + 80 * k):
            self.rr(rx, ry, x1, min(y1, ry + th_), 18 * k, mix(T["panel"], T["bg"], 0.1))
            self.text(rx + 20 * k, ry + 18 * k, "MOST PLAYED", self.font(12.5 * k, True), T["muted"])
        cx = rx + 20 * k
        fb = self.font(13 * k, True)
        for rid, lab in (("week", "Week"), ("month", "Month"), ("all", "All time")) if vis(ry, ry + 80 * k) else ():
            w = fb.measure(lab) + 26 * k
            on = rng == rid
            self.rr(cx, ry + 46 * k, cx + w, ry + 80 * k, 17 * k, T["accent"] if on else T["panel2"])
            self.text(cx + w / 2, ry + 63 * k, lab, fb, on_color(T["accent"]) if on else T["text"], anchor="center")
            self.region("pr_" + rid, cx, ry + 46 * k, cx + w, ry + 80 * k, lambda v=rid: self.set_cfg("play_range", v))
            cx += w + 8 * k
        by = ry + 96 * k
        if not games and vis(by, by + 20 * k):
            self.text(rx + 20 * k, by, "No sessions in this range yet", self.font(14 * k), T["muted"])
        top_s = games[0][1] if games else 1
        for name, sec, g in games:
            bw = (x1 - rx - 40 * k)
            if vis(by, by + 34 * k):
                self.rr(rx + 20 * k, by, x1 - 20 * k, by + 34 * k, 10 * k, T["panel2"])
                self.rr(rx + 20 * k, by, rx + 20 * k + max(20 * k, bw * sec / top_s), by + 34 * k, 10 * k, mix(T["panel2"], T["accent"], 0.5))
                self.text(rx + 32 * k, by + 17 * k, name, self.font(14 * k, True), T["text"], anchor="w", maxw=bw * 0.66)
                self.text(x1 - 32 * k, by + 17 * k, dc.fmt_duration(sec), self.font(13.5 * k), T["text"], anchor="e")
                if g:
                    self.region("pt_" + g["id"], rx + 20 * k, by, x1 - 20 * k, by + 34 * k, lambda gid=g["id"]: self.open_game(gid))
            by += 44 * k
        # badges
        bdy = ry + th_ + 16 * k
        bl = self.badges()
        got = sum(1 for b in bl if b[3] >= b[4])
        bh = 54 * k
        if vis(bdy, bdy + 46 * k):
            self.rr(rx, bdy, x1, min(y1, bdy + 46 * k + 4 * (bh + 8 * k) + 6 * k), 18 * k, mix(T["panel"], T["bg"], 0.1))
            self.text(rx + 20 * k, bdy + 16 * k, f"BADGES  ·  {got} OF {len(bl)}", self.font(12.5 * k, True), T["muted"])
        bw2 = (x1 - rx - 50 * k) / 2
        for i, (bid, name, desc, have, need) in enumerate(bl):
            r_, cn = divmod(i, 2)
            bx = rx + 20 * k + cn * (bw2 + 10 * k)
            by2 = bdy + 42 * k + r_ * (bh + 8 * k)
            if not vis(by2, by2 + bh):
                continue
            done = have >= need
            self.rr(bx, by2, bx + bw2, by2 + bh, 14 * k, mix(T["panel2"], T["accent"], 0.35) if done else T["panel2"])
            self.text(bx + 14 * k, by2 + 9 * k, ("✓ " if done else "") + name, self.font(14 * k, True),
                      T["text"] if done else T["muted"], maxw=bw2 - 24 * k)
            sub = desc if done or need == 1 else f"{desc}  ·  {int(have)}/{need}"
            self.text(bx + 14 * k, by2 + 31 * k, sub, self.font(11.5 * k), T["muted"] if not done else T["text"], maxw=bw2 - 24 * k)
        right_end = bdy + 46 * k + 4 * (bh + 8 * k) + 6 * k
        self.clamp_scroll("play", max(left_end, right_end) + off - top - (y1 - top))
        self.region("play_scroll", x0, top, x1, y1, None, scroll="play")

    # ------------------------------------------------------------------ Screenshots
    def shot_list(self):
        sel = self.cfg["shots_game"]
        return [x for x in self.shots or [] if not sel or x["appid"] == sel]

    def show_game_shots(self, g):
        self.cfg["shots_game"] = g["appid"]
        self.page = None
        self.set_tab("shots")

    def draw_shots(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        if self.shots is None:
            self.text((x0 + x1) / 2, (y0 + y1) / 2, "Looking for screenshots…", self.font(20 * k), T["muted"], anchor="center")
            return
        if not self.shots:
            self.text((x0 + x1) / 2, (y0 + y1) / 2 - 18 * k, "No screenshots yet", self.font(24 * k, True), T["text"], anchor="center")
            self.text((x0 + x1) / 2, (y0 + y1) / 2 + 18 * k, "Press STEAM + R1 in a game to take one. They show up here.",
                      self.font(16 * k), T["muted"], anchor="center")
            return
        counts = {}
        for x in self.shots:
            counts[x["appid"]] = counts.get(x["appid"], 0) + 1
        chips = [(None, f"All  ·  {len(self.shots)}")]
        for aid, n in sorted(counts.items(), key=lambda kv: -kv[1])[:6]:
            g = self.game_by_appid(aid)
            chips.append((aid, f"{g['name'] if g else 'App ' + aid}  ·  {n}"))
        sel = self.cfg["shots_game"]
        if sel and sel not in [c[0] for c in chips]:
            g = self.game_by_appid(sel)
            chips.append((sel, f"{g['name'] if g else 'App ' + sel}  ·  {counts.get(sel, 0)}"))
        x = x0
        f = self.font(14 * k, True)
        for aid, lab in chips:
            w = min(f.measure(lab) + 30 * k, 260 * k)
            if x + w > x1:
                break
            on = sel == aid
            self.rr(x, y0, x + w, y0 + 38 * k, 19 * k, T["accent"] if on else T["panel2"])
            self.text(x + w / 2, y0 + 19 * k, lab, f, on_color(T["accent"]) if on else T["text"], anchor="center", maxw=w - 20 * k)
            self.region(f"sf_{aid}", x, y0, x + w, y0 + 38 * k, lambda v=aid: self.set_cfg("shots_game", v, scroll="shots"))
            x += w + 8 * k
        items = self.shot_list()
        gy = y0 + 54 * k
        cols, gap = 4, 16 * k
        tw = (x1 - x0 - gap * (cols - 1)) / cols
        th = tw * 9 / 16
        rowh = th + 34 * k + gap
        off = self.clamp_scroll("shots", math.ceil(len(items) / cols) * rowh - (y1 - gy))
        for i, it in enumerate(items):
            r_, cn = divmod(i, cols)
            tx, ty = x0 + cn * (tw + gap), gy + r_ * rowh - off
            if ty < gy - 2 or ty > y1:
                continue
            img = self.image(it["thumb"], tw, th, 12 * k)
            if img:
                self.c.create_image(tx, ty, image=img, anchor="nw")
            else:
                self.rr(tx, ty, tx + tw, ty + th, 12 * k, T["panel2"])
            g = self.game_by_appid(it["appid"])
            lab = time.strftime("%b %d, %H:%M", time.localtime(it["t"]))
            if not sel:
                lab = (g["name"] if g else "App " + it["appid"]) + "  ·  " + lab
            self.text(tx + 2 * k, ty + th + 8 * k, lab, self.font(12.5 * k), T["muted"], maxw=tw)
            self.region(f"sh_{i}", tx, ty, tx + tw, ty + th, lambda i_=i: self.open_shot(i_))
        self.region("shots_scroll", x0, gy, x1, y1, None, scroll="shots")

    def open_shot(self, i):
        self.page = ("shot", i)
        self.redraw()

    def step_shot(self, d):
        items = self.shot_list()
        if items and self.page and self.page[0] == "shot":
            self.page = ("shot", (self.page[1] + d) % len(items))
            self.redraw()

    def draw_shot_view(self, i):
        T, k, c = self.t, self.k, self.c
        W, H = self.W, self.H
        items = self.shot_list()
        if not items:
            self.page = None
            return self.redraw()
        i = min(i, len(items) - 1)
        it = items[i]
        c.create_rectangle(0, 0, W, H, fill="#000000", outline="")
        key = ("full", it["path"], W, H)
        if key not in self.imgs:
            try:
                im = Image.open(it["path"])
                im.draft("RGB", (W, H))
                im = im.convert("RGB")
                sc = min(W / im.width, H / im.height)
                im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))), Image.LANCZOS)
                self.imgs[key] = ImageTk.PhotoImage(im)
            except Exception:
                self.imgs[key] = None
        if self.imgs[key]:
            c.create_image(W / 2, H / 2, image=self.imgs[key])
        g = self.game_by_appid(it["appid"])
        self.rr(24 * k, 20 * k, W - 24 * k, 72 * k, 26 * k, mix("#000000", T["panel"], 0.6))
        self.button("sv_back", 30 * k, 26 * k, 140 * k, 66 * k, "‹  BACK", self.close_page, "ghost")
        self.text(160 * k, 46 * k, f"{g['name'] if g else 'App ' + it['appid']}  ·  {time.strftime('%b %d %Y, %H:%M', time.localtime(it['t']))}"
                  f"  ·  {i + 1} of {len(items)}", self.font(15 * k, True), "#ffffff", anchor="w", maxw=W - 480 * k)
        self.button("sv_prev", W - 300 * k, 26 * k, W - 170 * k, 66 * k, "‹  PREV", lambda: self.step_shot(-1), "ghost")
        self.button("sv_next", W - 160 * k, 26 * k, W - 30 * k, 66 * k, "NEXT  ›", lambda: self.step_shot(1), "ghost")

    # ------------------------------------------------------------------ RAM: what is using memory, close what you don't need
    def open_ram(self):
        self.page = ("ram",)
        self.focus = None
        self.scan_ram()
        self.redraw()

    def scan_ram(self):
        def work():
            try:
                res = (dc.memory_info(), dc.memory_apps())
            except Exception:
                res = (None, [])
            self.call(lambda: (setattr(self, "ram", res), self.redraw()))
        self.background(work)

    def set_boost_app(self, name, mode):
        apps = dict(self.cfg["boost_apps"])
        if mode:
            apps[name] = mode
        else:
            apps.pop(name, None)
        self.cfg["boost_apps"] = apps
        self.redraw()

    def close_ram_app(self, app):
        n = dc.close_app(app["pids"])
        self.show_toast(f"Asked {app['name']} to close: about {dc.fmt_bytes(app['rss'])} back" if n else f"Couldn't close {app['name']}")
        self.root.after(1500, self.scan_ram)

    def close_all_ram(self, apps):
        n = sum(1 for a in apps if dc.close_app(a["pids"]))
        self.show_toast(f"Asked {n} app{'s' if n != 1 else ''} to close: about {dc.fmt_bytes(sum(a['rss'] for a in apps))} back")
        self.root.after(1500, self.scan_ram)

    def draw_ram(self):
        T, k = self.t, self.k
        W, H = self.W, self.H
        x0, x1 = 48 * k, W - 48 * k
        self.button("ram_back", 32 * k, 26 * k, 140 * k, 68 * k, "‹  BACK", self.close_page, "ghost")
        self.text(160 * k, 47 * k, "GAME BOOST", self.font(22 * k, True), T["text"], anchor="w")
        self.button("ram_boost", x1 - 380 * k, 28 * k, x1 - 190 * k, 66 * k, "BOOST NOW", self.boost, "accent", 13)
        self.button("ram_rescan", x1 - 170 * k, 28 * k, x1, 66 * k, "CHECK AGAIN", self.scan_ram, "normal", 13)
        if self.ram is None:
            self.text(W / 2, H / 2, "Looking at memory…", self.font(20 * k), T["muted"], anchor="center")
            return
        info, apps = self.ram
        y = 96 * k
        if info:
            used = info["total"] - info["avail"]
            self.rr(x0, y, x1, y + 120 * k, 20 * k, mix(T["panel"], T["bg"], 0.1))
            self.text(x0 + 22 * k, y + 18 * k, f"{dc.fmt_bytes(used)} in use of {dc.fmt_bytes(info['total'])}", self.font(24 * k, True), T["text"])
            frac = used / info["total"]
            self.rr(x0 + 22 * k, y + 60 * k, x1 - 22 * k, y + 76 * k, 8 * k, T["panel2"])
            self.rr(x0 + 22 * k, y + 60 * k, x0 + 22 * k + (x1 - x0 - 44 * k) * frac, y + 76 * k, 8 * k,
                    T["danger"] if frac > 0.9 else T["warn"] if frac > 0.75 else T["accent"])
            sub = f"{dc.fmt_bytes(info['avail'])} free for games"
            if info["swap_total"]:
                sub += f"  ·  swap {dc.fmt_bytes(info['swap_used'])} of {dc.fmt_bytes(info['swap_total'])}"
            sub += f"  ·  {dc.fmt_bytes(info['cached'])} is cache Linux hands back by itself when a game needs it"
            self.text(x0 + 22 * k, y + 90 * k, sub, self.font(13.5 * k), T["muted"], maxw=x1 - x0 - 44 * k)
            y += 136 * k
        # automatic: when a game starts, and when memory runs low while playing
        self.rr(x0, y, x1, y + 58 * k, 16 * k, mix(T["panel"], T["bg"], 0.1))
        on = self.cfg["boost_auto"]
        self.text(x0 + 20 * k, y + 29 * k, "When a game starts", self.font(15 * k, True), T["text"], anchor="w")
        self.button("ram_auto", x0 + 210 * k, y + 11 * k, x0 + 300 * k, y + 47 * k, "ON" if on else "OFF",
                    lambda: self.set_cfg("boost_auto", not self.cfg["boost_auto"]), "accent" if on else "normal", 13)
        self.text(x0 + 340 * k, y + 29 * k, "If memory gets low", self.font(15 * k, True), T["text"], anchor="w")
        self.chip_row("guard", x0 + 520 * k, y + 10 * k, [(0, "Off"), (10, "Under 10%"), (15, "Under 15%"), (20, "Under 20%")],
                      self.cfg["boost_guard"], lambda v: self.set_cfg("boost_guard", v), x1 - 10 * k)
        y += 72 * k
        names = {a["name"] for a in apps}
        apps = apps + [{"name": n, "pids": [], "rss": 0, "gone": True} for n in self.cfg["boost_apps"] if n not in names]
        tot = sum(a["rss"] for a in apps)
        self.text(x0, y, f"BACKGROUND APPS  ·  {dc.fmt_bytes(tot)}" if apps else "BACKGROUND APPS", self.font(13 * k, True), T["muted"])
        if len([a for a in apps if not a.get("gone")]) > 1:
            apps_live = [a for a in apps if not a.get("gone")]
            armed = self.is_armed("ram_all")
            self.button("ram_all", x1 - 220 * k, y - 10 * k, x1, y + 28 * k, "TAP AGAIN" if armed else "CLOSE ALL",
                        lambda: self.confirm("ram_all", lambda: self.close_all_ram(apps_live), "Tap again to close every app listed"),
                        "danger" if armed else "normal", 13)
        y += 34 * k
        if not apps:
            self.text(x0, y, "Nothing to close: no apps of yours are running in the background. "
                      "Apps you start in Desktop Mode (a browser, Discord) show up here.", self.font(15 * k), T["good"], maxw=x1 - x0)
            y += 30 * k
        off = self.scroll.get("ram", 0)
        top = y
        y -= off
        for i, a in enumerate(apps[:30]):
            if y >= top - 2 and y < H - 60 * k:
                self.rr(x0, y, x1, y + 56 * k, 14 * k, mix(T["panel"], T["bg"], 0.1))
                self.text(x0 + 18 * k, y + 28 * k, a["name"], self.font(15 * k, True), T["text"], anchor="w", maxw=(x1 - x0) * 0.45)
                if not a.get("gone"):
                    self.text(x0 + (x1 - x0) * 0.3, y + 28 * k,
                              f"{dc.fmt_bytes(a['rss'])}  ·  {len(a['pids'])} process{'es' if len(a['pids']) != 1 else ''}",
                              self.font(14 * k), T["muted"], anchor="w")
                mode = self.cfg["boost_apps"].get(a["name"], "")
                self.text(x0 + (x1 - x0) * 0.5, y + 28 * k, "Boost:", self.font(13 * k, True), T["muted"], anchor="w")
                self.chip_row(f"bm{i}", x0 + (x1 - x0) * 0.5 + 60 * k, y + 9 * k, [("", "Leave"), ("close", "Close"), ("pause", "Freeze")],
                              mode, lambda v, n=a["name"]: self.set_boost_app(n, v))
                key = "ram_" + a["name"]
                armed = self.is_armed(key)
                if not a.get("gone"):
                    self.button(f"ramc_{i}", x1 - 150 * k, y + 9 * k, x1 - 12 * k, y + 47 * k, "TAP AGAIN" if armed else "CLOSE NOW",
                                lambda a_=a, k_=key: self.confirm(k_, lambda: self.close_ram_app(a_), f"Tap again to close {a_['name']}"),
                                "danger" if armed else "normal", 13)
                else:
                    self.text(x1 - 20 * k, y + 28 * k, "not running", self.font(13 * k), T["muted"], anchor="e")
            y += 64 * k
        self.clamp_scroll("ram", y + off - top - (H - 60 * k - top))
        self.region("ram_scroll", x0, top, x1, H, None, scroll="ram")
        st = self.cfg["boost_stats"]
        self.text(x0, H - 30 * k, (f"Freed about {dc.fmt_bytes(st.get('freed', 0))} over {st.get('times', 0)} boosts.  " if st.get("times") else "") +
                  "Freeze pauses an app while you play and wakes it when you stop. Steam, Game Mode and your game are never listed.",
                  self.font(12.5 * k), T["muted"], maxw=x1 - x0)

    # ------------------------------------------------------------------ Game Boost: close or freeze the apps you picked
    def boost(self, auto=False, reason=None):
        """Runs off the UI thread; reports back with a toast."""
        picks = dict(self.cfg["boost_apps"])
        if not picks:
            if not auto:
                self.show_toast("Pick apps on the Game Boost page first (Tools › Game Boost)")
            return

        def work():
            try:
                apps = dc.memory_apps(min_bytes=0)
            except Exception:
                apps = []
            closed, paused, freed = [], [], 0
            for a in apps:
                mode = picks.get(a["name"])
                if mode == "close" and dc.close_app(a["pids"]):
                    closed.append(a["name"])
                    freed += a["rss"]
                elif mode == "pause" and self.running and dc.pause_app(a["pids"], True):
                    paused.append({"name": a["name"], "pids": a["pids"]})
                    freed += a["rss"]
            self.call(lambda: self.boost_done(closed, paused, freed, auto, reason))
        self.boosted = True
        self.background(work)

    def boost_done(self, closed, paused, freed, auto, reason):
        if paused:
            self.cfg["paused"] = self.cfg["paused"] + paused
        st = dict(self.cfg["boost_stats"])
        if closed or paused:
            st["freed"] = st.get("freed", 0) + freed
            st["times"] = st.get("times", 0) + 1
            self.cfg["boost_stats"] = st
            bits = []
            if closed:
                bits.append(f"closed {', '.join(closed)}")
            if paused:
                bits.append(f"froze {', '.join(p['name'] for p in paused)}")
            self.show_toast(f"{reason or 'Game Boost'}: {' and '.join(bits)}, about {dc.fmt_bytes(freed)} back")
        elif not auto:
            self.show_toast("Game Boost: none of your picked apps are running")
        if self.page and self.page[0] == "ram":
            self.root.after(1200, self.scan_ram)

    def wake_paused(self, quiet=False):
        if not self.cfg["paused"]:
            return
        names = []
        for it in self.cfg["paused"]:
            if dc.pause_app(it.get("pids", []), False):
                names.append(it.get("name", "?"))
        self.cfg["paused"] = []
        if names and not quiet:
            self.show_toast(f"Woke up {', '.join(dict.fromkeys(names))}")

    def check_env(self):
        """Every few seconds, off the UI thread: TV / dock, and the low-memory guard while a game runs."""
        docked = dc.external_display()
        low = None
        if self.running and self.cfg["boost_guard"] and not self.boosted:
            info = dc.memory_info()
            if info and info["avail"] / info["total"] * 100 < self.cfg["boost_guard"]:
                low = info

        def back():
            if docked != self.docked:
                self.docked = docked
                self.redraw()
            if low and not self.boosted:
                self.boost(auto=True, reason="Memory was low")
        self.call(back)

    # ------------------------------------------------------------------ phone app
    def set_remote(self, on, quiet=False):
        if on and not self.remote:
            if not self.cfg["remote_pin"]:
                self.cfg["remote_pin"] = f"{random.SystemRandom().randint(0, 999999):06d}"
            try:
                self.remote = deck_remote.Remote(RemoteBridge(self))
            except OSError:
                self.remote = None
                self.cfg["remote"] = False
                if not quiet:
                    self.show_toast(f"Couldn't start the phone app: port {deck_remote.PORT} is busy")
                return
            self.cfg["remote"] = True
            self.remote_ip = dc.lan_ip()
        elif not on and self.remote:
            self.remote.stop()
            self.remote = None
            self.cfg["remote"] = False
        self.redraw()

    def state(self):
        """For the phone: a snapshot of what's on screen (called from the server thread, so read-only)."""
        s = self.stats or {}
        b = s.get("batt") or {}
        g = self.game_by_appid(next(iter(self.running))) if self.running else None
        mem = s.get("mem")
        u = (lambda v: f"{v * 9 / 5 + 32:.0f}°F") if self.cfg["fahrenheit"] else (lambda v: f"{v:.0f}°C")
        st = self.cfg["boost_stats"]
        lib = self.recent()[:30] if not self.cfg["guest"] else []
        return {"clock": time.strftime("%H:%M"), "game": g["name"] if g else (f"App {next(iter(self.running))}" if self.running else None),
                "game_for": dc.fmt_duration(time.time() - next(iter(self.running.values()))) if self.running else "",
                "batt": {"pct": b.get("pct"), "text": (b.get("status", "").lower() + (f" · {b['watts']:.1f} W" if b.get("watts") else "") +
                                                       (f" · {dc.fmt_duration(b['left'])} left" if b.get("left") else ""))},
                "today": dc.fmt_duration(self.played_today()), "streak": self.streak(),
                "cpu": round(s["cpu"]) if s.get("cpu") is not None else None, "gpu": round(s["gpu"]) if s.get("gpu") is not None else None,
                "cpu_temp": u(s["cpu_temp"]) if s.get("cpu_temp") else "", "gpu_temp": u(s["gpu_temp"]) if s.get("gpu_temp") else "",
                "ram_text": f"{mem[0] / 2**30:.1f} of {mem[1] / 2**30:.0f} GB" if mem else "–",
                "ram_pct": round(mem[0] / mem[1] * 100) if mem else 0,
                "boost_text": (f"Freed about {dc.fmt_bytes(st.get('freed', 0))} over {st.get('times', 0)} boosts" if st.get("times")
                               else "Pick apps to close or freeze in Vanta Deck › Tools › Game Boost"),
                "goal": self.goal_text()[0] if self.cfg["batt_goal"] else None,
                "games": [{"id": x["id"], "name": x["name"], "cover": bool(x["cover"])} for x in lib]}

    def action(self, a, v):
        if a == "play":
            g = self.game(str(v))
            if not g:
                return "Game not found"
            self.call(lambda: self.play(g))
            return f"Starting {g['name']} on the Deck"
        if a == "boost":
            if not self.cfg["boost_apps"]:
                return "Pick apps on the Deck first: Tools › Game Boost"
            self.call(lambda: self.boost())
            return "Game Boost running"
        return "Unknown action"



    # ------------------------------------------------------------------ battery goal
    def goal_text(self):
        """(headline, detail lines, state) for the battery goal."""
        end = self.cfg["batt_goal"]
        b = (self.stats or {}).get("batt") or {}
        if not end:
            return None, [], None
        left_s = end - time.time()
        if left_s <= 0:
            return "Goal reached", ["You made it. Set a new goal any time."], "good"
        if not b or not b.get("full_wh") or b.get("pct") is None:
            return "No battery reading yet", [], None
        if b.get("status") != "Discharging":
            return f"Until {time.strftime('%H:%M', time.localtime(end))}: plugged in", ["The goal counts once you unplug."], None
        wh = b["full_wh"] * b["pct"] / 100
        need = wh / (left_s / 3600)
        h = self.sensors.hist.get("watts") or []
        now_w = sum(h[-30:]) / len(h[-30:]) if h else b.get("watts") or 0
        lines = [f"{wh:.1f} Wh left for {dc.fmt_duration(left_s)}: you can use about {need:.1f} W on average",
                 f"Right now the Deck draws {now_w:.1f} W"]
        if not now_w or now_w <= need:
            return f"On track for {time.strftime('%H:%M', time.localtime(end))}", lines, "good"
        tdp = max(3, min(15, int(need - 3.5)))
        lines += [f"Open the Quick Access menu (…) › Performance and set a TDP limit of about {tdp} W",
                  "A frame limit of 30 or 40 fps and lower brightness help too"]
        return f"Short by about {dc.fmt_duration(left_s - wh / now_w * 3600)} at this rate", lines, "warn"

    def set_goal(self, hours):
        self.cfg["batt_goal"] = time.time() + hours * 3600 if hours else None
        self.redraw()

    # ------------------------------------------------------------------ Tools tab
    def tools(self):
        st = self.cfg["boost_stats"]
        return [("tool_boost", "Game Boost", "Close or freeze the apps you pick when a game starts" +
                 (f"  ·  freed {dc.fmt_bytes(st.get('freed', 0))} so far" if st.get("times") else ""),
                 "AUTO" if self.cfg["boost_auto"] else None, self.open_ram),
                ("tool_goal", "Battery goal", "Play until a time you pick: Vanta tells you what to change to make it",
                 "ON" if self.cfg["batt_goal"] else None, lambda: self.open_page("goal")),
                ("tool_remote", "Phone app", "Stats, your games and Game Boost from your phone's browser",
                 "ON" if self.remote else None, lambda: self.open_page("remote")),
                ("tool_startup", "Startup apps", "What starts with Desktop Mode: turn off what you don't need",
                 None, lambda: (self.load_startup(), self.open_page("startup"))),
                ("tool_pad", "Controller test", "See every button and stick live, and check for drift", None, lambda: self.open_page("pad")),
                ("tool_backup", "Backup & restore", "Save your notes, ratings, sessions and settings to a file",
                 None, lambda: (self.load_backups(), self.open_page("backup"))),
                ("tool_guest", "Guest mode", "Someone else playing? Nothing is tracked and your notes are hidden",
                 "ON" if self.cfg["guest"] else "OFF", self.toggle_guest),
                ("tool_tv", "TV mode", "Bigger text automatically when a TV or monitor is plugged in" +
                 ("  ·  connected now" if self.docked else ""), "ON" if self.cfg["tv_auto"] else "OFF",
                 lambda: self.set_cfg("tv_auto", not self.cfg["tv_auto"]))]

    def toggle_guest(self):
        self.cfg["guest"] = not self.cfg["guest"]
        self.show_toast("Guest mode on: nothing is tracked, notes are hidden" if self.cfg["guest"] else "Guest mode off")
        self.redraw()

    def open_page(self, name):
        self.page = (name,)
        self.focus = None
        self.hide_entry()
        self.redraw()

    def draw_tools(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        items = self.tools()
        cols, gap = 4, 16 * k
        tw = (x1 - x0 - gap * (cols - 1)) / cols
        th = (y1 - y0 - gap) / 2
        for i, (rid, title, sub, badge, fn) in enumerate(items):
            r_, cn = divmod(i, cols)
            tx, ty = x0 + cn * (tw + gap), y0 + r_ * (th + gap)
            on = badge in ("ON", "AUTO")
            self.rr(tx, ty, tx + tw, ty + th, 20 * k, mix(T["panel"], T["accent"], 0.12) if on else mix(T["panel"], T["bg"], 0.1))
            self.text(tx + 22 * k, ty + 22 * k, title, self.font(19 * k, True), T["text"], maxw=tw - 44 * k)
            for j, line in enumerate(self.wrap(sub, self.font(14 * k), tw - 44 * k)[:5]):
                self.text(tx + 22 * k, ty + 58 * k + j * 21 * k, line, self.font(14 * k), T["muted"])
            if badge:
                f = self.font(13 * k, True)
                w = f.measure(badge) + 26 * k
                self.rr(tx + 22 * k, ty + th - 54 * k, tx + 22 * k + w, ty + th - 22 * k, 16 * k, T["accent"] if on else T["panel2"])
                self.text(tx + 22 * k + w / 2, ty + th - 38 * k, badge, f, on_color(T["accent"]) if on else T["muted"], anchor="center")
            self.region(rid, tx, ty, tx + tw, ty + th, fn)

    def page_header(self, title, sub=None):
        T, k = self.t, self.k
        self.button("pg_back", 32 * k, 26 * k, 140 * k, 68 * k, "‹  BACK", self.close_page, "ghost")
        self.text(160 * k, 47 * k, title, self.font(22 * k, True), T["text"], anchor="w")
        if sub:
            self.text(160 * k, 80 * k, sub, self.font(14 * k), T["muted"], anchor="w", maxw=self.W - 220 * k)

    def chip_row(self, prefix, x, y, items, cur, fn, x1=None):
        T, k = self.t, self.k
        f = self.font(14 * k, True)
        for val, lab in items:
            w = f.measure(lab) + 30 * k
            if x1 and x + w > x1:
                break
            on = val == cur
            self.rr(x, y, x + w, y + 38 * k, 19 * k, T["accent"] if on else T["panel2"])
            self.text(x + w / 2, y + 19 * k, lab, f, on_color(T["accent"]) if on else T["text"], anchor="center")
            self.region(f"{prefix}_{val}", x, y, x + w, y + 38 * k, lambda v=val: fn(v))
            x += w + 8 * k
        return x

    # battery goal page
    def draw_goal(self):
        T, k = self.t, self.k
        x0, x1 = 48 * k, self.W - 48 * k
        self.page_header("BATTERY GOAL", "Pick how long you want to play. Vanta works out whether the battery makes it.")
        y = 120 * k
        left = (self.cfg["batt_goal"] - time.time()) / 3600 if self.cfg["batt_goal"] else None
        opts = [(0, "Off"), (1, "1 hour"), (1.5, "1h 30m"), (2, "2 hours"), (2.5, "2h 30m"), (3, "3 hours"), (4, "4 hours")]
        self.chip_row("goal", x0, y, opts, None if left is None else min(opts[1:], key=lambda o: abs(o[0] - left))[0] if left > 0 else 0,
                      self.set_goal, x1)
        y += 64 * k
        head, lines, state = self.goal_text()
        if head:
            self.rr(x0, y, x1, y + 70 * k + len(lines) * 30 * k, 20 * k, mix(T["panel"], T["bg"], 0.1))
            self.text(x0 + 24 * k, y + 20 * k, head, self.font(26 * k, True), T.get(state, T["text"]) if state else T["text"])
            for i, line in enumerate(lines):
                self.text(x0 + 24 * k, y + 66 * k + i * 30 * k, line, self.font(16 * k), T["text"] if i < 2 else T["muted"], maxw=x1 - x0 - 48 * k)
            y += 90 * k + len(lines) * 30 * k
        else:
            self.text(x0, y, "No goal set.", self.font(18 * k), T["muted"])
            y += 50 * k
        # per-game battery life from what Vanta has measured
        known = sorted(((pw[0] / pw[1], aid) for aid, pw in self.cfg["power"].items() if pw[1] >= 60))
        b = (self.stats or {}).get("batt") or {}
        if known and b.get("full_wh"):
            self.text(x0, y, "HOW LONG A FULL CHARGE LASTS, BY GAME", self.font(13 * k, True), T["muted"])
            y += 30 * k
            for w, aid in known[:8]:
                g = self.game_by_appid(aid)
                self.rr(x0, y, x1, y + 46 * k, 12 * k, mix(T["panel"], T["bg"], 0.1))
                self.text(x0 + 18 * k, y + 23 * k, g["name"] if g else f"App {aid}", self.font(15 * k, True), T["text"], anchor="w",
                          maxw=(x1 - x0) * 0.5)
                self.text(x1 - 18 * k, y + 23 * k, f"{w:.1f} W  ·  about {dc.fmt_duration(b['full_wh'] / w * 3600)}", self.font(15 * k),
                          T["text"], anchor="e")
                y += 52 * k
                if y > self.H - 60 * k:
                    break
        self.text(x0, self.H - 30 * k, "Vanta can't change power limits itself on SteamOS: it tells you what to set in Steam's Performance menu.",
                  self.font(12.5 * k), T["muted"], maxw=x1 - x0)

    # phone app page
    def draw_remote(self):
        T, k = self.t, self.k
        x0, x1 = 48 * k, self.W - 48 * k
        self.page_header("PHONE APP", "Open Vanta Deck on your phone: same Wi-Fi, any browser.")
        y = 120 * k
        on = bool(self.remote)
        self.button("rm_toggle", x0, y, x0 + 260 * k, y + 54 * k, "TURN OFF" if on else "TURN ON", lambda: self.set_remote(not on),
                    "normal" if on else "accent")
        y += 84 * k
        if on:
            ip = getattr(self, "remote_ip", None) or "your-deck-ip"
            self.rr(x0, y, x1, y + 200 * k, 20 * k, mix(T["panel"], T["bg"], 0.1))
            self.text(x0 + 24 * k, y + 22 * k, "ON YOUR PHONE, OPEN", self.font(13 * k, True), T["muted"])
            self.text(x0 + 24 * k, y + 46 * k, f"http://{ip}:{deck_remote.PORT}", self.font(34 * k, True), T["accent"])
            self.text(x0 + 24 * k, y + 110 * k, "PIN", self.font(13 * k, True), T["muted"])
            self.text(x0 + 24 * k, y + 134 * k, " ".join(self.cfg["remote_pin"]), self.font(34 * k, True), T["text"])
            self.button("rm_newpin", x1 - 220 * k, y + 134 * k, x1 - 24 * k, y + 176 * k, "NEW PIN",
                        lambda: self.confirm("newpin", self.new_pin, "Tap again: phones will need the new PIN"), "normal", 13)
            y += 230 * k
            self.text(x0, y, "Your phone can see stats and your games, start a game, run Game Boost and look at your screenshots. "
                      "Nothing leaves your home network.", self.font(15 * k), T["muted"], maxw=x1 - x0)
        else:
            self.text(x0, y, "Off. When it's on, phones on your Wi-Fi with the PIN can see your stats and start games.",
                      self.font(16 * k), T["muted"], maxw=x1 - x0)

    def new_pin(self):
        self.cfg["remote_pin"] = f"{random.SystemRandom().randint(0, 999999):06d}"
        self.redraw()

    # startup apps
    def load_startup(self):
        try:
            self.startup = dc.startup_apps()
        except Exception:
            self.startup = []

    def flip_startup(self, it):
        if dc.set_startup(it, not it["on"]):
            self.show_toast(f"{it['name']} {'starts with Desktop Mode again' if not it['on'] else 'no longer starts with Desktop Mode'}")
        else:
            self.show_toast(f"Couldn't change {it['name']}")
        self.load_startup()
        self.redraw()

    def draw_startup(self):
        T, k = self.t, self.k
        x0, x1 = 48 * k, self.W - 48 * k
        self.page_header("STARTUP APPS", "Apps that open by themselves in Desktop Mode. Game Mode doesn't run these.")
        y = 120 * k
        items = self.startup or []
        if not items:
            self.text(x0, y, "Nothing starts with Desktop Mode.", self.font(17 * k), T["good"])
            return
        for i, it in enumerate(items[:12]):
            self.rr(x0, y, x1, y + 56 * k, 14 * k, mix(T["panel"], T["bg"], 0.1))
            self.text(x0 + 18 * k, y + 28 * k, it["name"], self.font(16 * k, True), T["text"] if it["on"] else T["muted"], anchor="w",
                      maxw=(x1 - x0) * 0.6)
            self.button(f"su_{i}", x1 - 150 * k, y + 9 * k, x1 - 12 * k, y + 47 * k, "ON" if it["on"] else "OFF",
                        lambda it_=it: self.flip_startup(it_), "accent" if it["on"] else "normal", 13)
            y += 64 * k
        self.text(x0, self.H - 30 * k, "Turned-off apps are kept in Vanta's folder, so turning them back on restores them exactly.",
                  self.font(12.5 * k), T["muted"])

    # controller test
    def draw_pad(self):
        T, k = self.t, self.k
        x0, x1 = 48 * k, self.W - 48 * k
        self.page_header("CONTROLLER TEST", "Press buttons and move the sticks. Press B twice to leave.")
        raw = getattr(self.joy, "raw", {"buttons": {}, "axes": {}})
        if not getattr(self, "_pad_timer", False):
            self._pad_timer = True

            def again():
                self._pad_timer = False
                if self.page and self.page[0] == "pad":
                    self.redraw()
            self.root.after(70, again)
        y = 120 * k
        if not self.joy.name:
            self.text(x0, y, "No controller found. In Desktop Mode Steam may be turning the controls into a mouse and keyboard: "
                      "this test works best in Game Mode.", self.font(16 * k), T["warn"], maxw=x1 - x0)
            y += 60 * k
        else:
            self.text(x0, y, f"Reading {self.joy.name}", self.font(14 * k), T["muted"])
            y += 34 * k
        names = {0: "A", 1: "B", 2: "X", 3: "Y", 4: "L1", 5: "R1", 6: "View", 7: "Menu", 8: "Steam", 9: "L3", 10: "R3",
                 11: "Left", 12: "Right", 13: "Up", 14: "Down"}
        bx = x0
        for num in sorted(set(names) | set(raw["buttons"])):
            on = raw["buttons"].get(num)
            lab = names.get(num, f"B{num}")
            w = max(64 * k, self.font(15 * k, True).measure(lab) + 30 * k)
            if bx + w > x1:
                bx = x0
                y += 56 * k
            self.rr(bx, y, bx + w, y + 46 * k, 14 * k, T["accent"] if on else T["panel2"])
            self.text(bx + w / 2, y + 23 * k, lab, self.font(15 * k, True), on_color(T["accent"]) if on else T["text"], anchor="center")
            bx += w + 10 * k
        y += 80 * k
        sticks = [("Left stick", 0, 1), ("Right stick", 3, 4)]
        R = 90 * k
        for i, (lab, ax, ay) in enumerate(sticks):
            cx = x0 + R + 20 * k + i * (2 * R + 120 * k)
            cy = y + R + 30 * k
            self.text(cx, y, lab, self.font(14 * k, True), T["muted"], anchor="n")
            self.c.create_oval(cx - R, cy - R, cx + R, cy + R, outline=T["line"], width=2, fill=mix(T["panel"], T["bg"], 0.1))
            self.c.create_oval(cx - R * 0.08, cy - R * 0.08, cx + R * 0.08, cy + R * 0.08, outline=T["muted"])
            vx, vy = raw["axes"].get(ax, 0) / 32767, raw["axes"].get(ay, 0) / 32767
            px, py = cx + vx * R, cy + vy * R
            self.c.create_oval(px - 12 * k, py - 12 * k, px + 12 * k, py + 12 * k, fill=T["accent"], outline="")
            dist = min(1, math.hypot(vx, vy))
            self.text(cx, cy + R + 14 * k, f"{dist * 100:.0f}% off center" + ("  ·  drift?" if 0.08 < dist < 0.3 else ""),
                      self.font(13.5 * k), T["warn"] if 0.08 < dist < 0.3 else T["muted"], anchor="n")
        tx = x0 + 4 * (R + 60 * k) + 40 * k
        for i, (lab, ax) in enumerate((("L2", 2), ("R2", 5))):
            v = (raw["axes"].get(ax, -32767) + 32767) / 65534
            yy = y + 40 * k + i * 70 * k
            self.text(tx, yy, lab, self.font(14 * k, True), T["muted"])
            self.rr(tx + 50 * k, yy, x1, yy + 26 * k, 13 * k, T["panel2"])
            self.rr(tx + 50 * k, yy, tx + 50 * k + (x1 - tx - 50 * k) * max(0.02, v), yy + 26 * k, 13 * k, T["accent"])
        self.text(x0, self.H - 30 * k, "A stick that sits more than 8% off center when you're not touching it is drifting: "
                  "Steam › Settings › Controller › Calibration fixes most of it.", self.font(12.5 * k), T["muted"], maxw=x1 - x0)

    # backups
    def load_backups(self):
        try:
            self.backups = dc.backups()
        except Exception:
            self.backups = []

    def make_backup(self):
        try:
            p = dc.backup(dict(self.cfg))
            self.show_toast(f"Saved to Documents › Vanta Deck backups › {os.path.basename(p)}")
        except OSError as e:
            self.show_toast(f"Couldn't save the backup: {e.strerror}")
        self.load_backups()
        self.redraw()

    def restore(self, path):
        data = dc.read_backup(path)
        if not data:
            self.show_toast("That file isn't a Vanta Deck backup")
            return
        pin = self.cfg["remote_pin"]
        for k_, v in data.items():
            if k_ in dc.DEFAULTS and (dc.DEFAULTS[k_] is None or type(v) is type(dc.DEFAULTS[k_])):
                self.cfg[k_] = v
        self.cfg["remote_pin"] = pin
        self.cfg["paused"] = []
        self.fx = None
        self.imgs = {}
        self.show_toast("Restored: notes, ratings, sessions and settings are back")
        self.redraw()

    def draw_backup(self):
        T, k = self.t, self.k
        x0, x1 = 48 * k, self.W - 48 * k
        self.page_header("BACKUP & RESTORE", "Notes, ratings, sessions, badges and settings. Saved in Documents › Vanta Deck backups.")
        y = 120 * k
        self.button("bk_make", x0, y, x0 + 280 * k, y + 54 * k, "MAKE A BACKUP", self.make_backup, "accent")
        y += 84 * k
        items = self.backups or []
        if not items:
            self.text(x0, y, "No backups yet.", self.font(16 * k), T["muted"])
        for i, p in enumerate(items[:8]):
            self.rr(x0, y, x1, y + 56 * k, 14 * k, mix(T["panel"], T["bg"], 0.1))
            try:
                when = time.strftime("%b %d %Y, %H:%M", time.localtime(os.path.getmtime(p)))
            except OSError:
                when = "?"
            self.text(x0 + 18 * k, y + 28 * k, when, self.font(16 * k, True), T["text"], anchor="w")
            self.text(x0 + 320 * k, y + 28 * k, os.path.basename(p), self.font(13.5 * k), T["muted"], anchor="w", maxw=(x1 - x0) * 0.45)
            key = "rs_" + p
            armed = self.is_armed(key)
            self.button(f"rs_{i}", x1 - 170 * k, y + 9 * k, x1 - 12 * k, y + 47 * k, "TAP AGAIN" if armed else "RESTORE",
                        lambda p_=p, k_=key: self.confirm(k_, lambda: self.restore(p_), "Tap again: this replaces what's in Vanta now"),
                        "danger" if armed else "normal", 13)
            y += 64 * k
        self.text(x0, self.H - 30 * k, "The phone app PIN is never saved in a backup.", self.font(12.5 * k), T["muted"])

    # themes page
    def draw_themes(self):
        T, k = self.t, self.k
        x0, x1 = 48 * k, self.W - 48 * k
        self.page_header("THEMES", f"{len(THEMES)} themes  ·  ✦ moves gently")
        y = 112 * k
        x = self.chip_row("tf", x0, y, [("all", "All"), ("anim", "Animated"), ("dark", "Dark"), ("light", "Light")], self.theme_filter,
                          lambda v: (setattr(self, "theme_filter", v), self.scroll.__setitem__("themes", 0), self.redraw()))
        if self.cfg["day_night"]:
            x += 20 * k
            self.chip_row("ts", x, y, [("main", f"Night: {self.cfg['theme']}"), ("day", f"Day: {self.cfg['day_theme']}")], self.theme_slot,
                          lambda v: (setattr(self, "theme_slot", v), self.redraw()), x1)
        names = [n for n, t in THEMES.items() if self.theme_filter == "all" or (self.theme_filter == "anim" and t.get("fx"))
                 or (self.theme_filter == "dark" and not t.get("light")) or (self.theme_filter == "light" and t.get("light"))]
        gy = y + 56 * k
        cols, gap = 5, 12 * k
        tw = (x1 - x0 - gap * (cols - 1)) / cols
        th = 80 * k
        cur = self.cfg["day_theme"] if self.theme_slot == "day" and self.cfg["day_night"] else self.cfg["theme"]
        off = self.clamp_scroll("themes", math.ceil(len(names) / cols) * (th + gap) - (self.H - gy - 20 * k))
        for i, name in enumerate(names):
            th_ = THEMES[name]
            r_, cn = divmod(i, cols)
            tx, ty = x0 + cn * (tw + gap), gy + r_ * (th + gap) - off
            if ty < gy - 2 or ty + th > self.H:
                continue
            bg = th_["grad"][0] if th_.get("grad") else th_["bg"]
            self.rr(tx, ty, tx + tw, ty + th, 14 * k, bg, outline=T["accent"] if name == cur else th_["line"],
                    width=max(2, 3 * k) if name == cur else 1)
            self.rr(tx + 12 * k, ty + 12 * k, tx + 46 * k, ty + 30 * k, 9 * k, th_["accent"])
            self.rr(tx + 52 * k, ty + 12 * k, tx + 72 * k, ty + 30 * k, 9 * k, th_["accent2"])
            self.text(tx + 12 * k, ty + 44 * k, name + ("  ✦" if th_.get("fx") else ""), self.font(14 * k, True), th_["text"], maxw=tw - 20 * k)
            self.region("th_" + name, tx, ty, tx + tw, ty + th, lambda n=name: self.set_theme(n), scroll="themes")
        self.region("themes_scroll", x0, gy, x1, self.H, None, scroll="themes")

    # ------------------------------------------------------------------ updates
    @staticmethod
    def exe_path():
        return sys.executable if getattr(sys, "frozen", False) else None

    def check_update(self, quiet=False):
        if self.update_state in ("checking", "downloading") or isinstance(self.update_state, float):
            return
        self.update_state = "checking"
        if not quiet:
            self.redraw()

        def work():
            try:
                info = dc.check_update(VERSION)
                err = None
            except Exception as e:
                info, err = None, e.__class__.__name__
            self.call(lambda: self.update_checked(info, err, quiet))
        self.background(work)

    def update_checked(self, info, err, quiet):
        self.cfg["update_last"] = time.time()
        if err:
            self.update_state = f"error: couldn't reach GitHub ({err})"
        else:
            self.update = info
            self.update_state = None if info and info["newer"] else "latest"
            if info and info["newer"] and (not quiet or info["tag"] != self.cfg["update_skip"]):
                self.show_toast(f"Vanta Deck {info['version']} is out: Settings › Updates")
            elif not quiet:
                self.show_toast("You have the newest Vanta Deck")
        if quiet and self.update_state and self.update_state.startswith("error"):
            self.update_state = None
        self.redraw()

    def install_update(self):
        exe = self.exe_path()
        info = self.update
        if not exe or not info or not info.get("url"):
            return
        if not os.access(os.path.dirname(exe), os.W_OK):
            self.show_toast("Vanta can't write to its own folder: reinstall it with install.sh")
            return
        self.update_state = 0.0
        self.redraw()

        def prog(f):
            self.call(lambda: (setattr(self, "update_state", f), self.redraw()))

        def work():
            try:
                dc.install_update(info, exe, prog)
                self.call(lambda: self.update_done(None))
            except OSError as e:
                msg = str(e)
                self.call(lambda: self.update_done(msg))
        self.background(work)

    def update_done(self, err):
        if err:
            self.update_state = f"error: {err}"
            self.redraw()
            return
        self.update_state = "restarting"
        self.redraw()
        self.root.after(800, self.restart)

    def restart(self):
        """Start the (new) program in this same process, so Steam keeps treating it as the same app."""
        exe = self.exe_path()
        self.wake_paused(quiet=True)
        if self.remote:
            self.remote.stop()
        try:
            self.cfg.save()
        except OSError:
            pass
        self.joy.stop = True
        if not exe:
            return
        try:
            self.root.destroy()
        except Exception:
            pass
        os.execv(exe, [exe])

    def roll_back(self):
        exe = self.exe_path()
        if not exe or not os.path.exists(exe + ".old"):
            return
        try:
            os.replace(exe + ".old", exe)
        except OSError as e:
            self.show_toast(f"Couldn't go back: {e.strerror}")
            return
        self.show_toast("Going back to the previous version…")
        self.root.after(800, self.restart)

    def draw_update(self):
        T, k = self.t, self.k
        x0, x1 = 48 * k, self.W - 48 * k
        self.page_header("UPDATES", f"You have Vanta Deck {VERSION}. New versions come from GitHub: {dc.UPDATE_REPO}")
        y = 120 * k
        st = self.update_state
        info = self.update
        exe = self.exe_path()
        self.button("up_check", x0, y, x0 + 240 * k, y + 50 * k, "CHECKING…" if st == "checking" else "CHECK NOW",
                    self.check_update, "normal", 14)
        on = self.cfg["update_auto"]
        self.text(x0 + 270 * k, y + 25 * k, "Check by itself", self.font(15 * k, True), T["text"], anchor="w")
        self.button("up_auto", x0 + 420 * k, y + 7 * k, x0 + 510 * k, y + 43 * k, "ON" if on else "OFF",
                    lambda: self.set_cfg("update_auto", not self.cfg["update_auto"]), "accent" if on else "normal", 13)
        if self.cfg["update_last"]:
            self.text(x1, y + 25 * k, f"Last checked {dc.ago(self.cfg['update_last'])}", self.font(13.5 * k), T["muted"], anchor="e")
        y += 74 * k
        if isinstance(st, str) and st.startswith("error"):
            self.text(x0, y, st[7:].capitalize(), self.font(16 * k, True), T["danger"], maxw=x1 - x0)
            y += 40 * k
        if info:
            box_h = 250 * k
            self.rr(x0, y, x1, y + box_h, 20 * k, mix(T["panel"], T["accent"], 0.1) if info["newer"] else mix(T["panel"], T["bg"], 0.1))
            head = f"Vanta Deck {info['version']} is ready" if info["newer"] else f"You have the newest version ({VERSION})"
            self.text(x0 + 24 * k, y + 20 * k, head, self.font(26 * k, True), T["text"])
            meta = info["name"] + (f"  ·  {dc.fmt_bytes(info['size'])}" if info.get("size") else "") + \
                ("  ·  checksum verified on download" if info.get("sha256") else "")
            self.text(x0 + 24 * k, y + 60 * k, meta, self.font(14 * k), T["muted"])
            notes = [l.strip(" #*-") for l in info["notes"].splitlines() if l.strip() and not l.lower().startswith("sha256")]
            ny = y + 92 * k
            for line in notes[:5]:
                for part in self.wrap(line, self.font(14.5 * k), x1 - x0 - 48 * k)[:2]:
                    if ny > y + box_h - 30 * k:
                        break
                    self.text(x0 + 24 * k, ny, part, self.font(14.5 * k), T["text"])
                    ny += 22 * k
            y += box_h + 20 * k
            if info["newer"]:
                if not exe:
                    self.text(x0, y, "You're running Vanta Deck from source: update it with git pull instead.", self.font(16 * k), T["muted"])
                elif isinstance(st, float):
                    self.rr(x0, y, x1, y + 50 * k, 14 * k, T["panel2"])
                    self.rr(x0, y, x0 + (x1 - x0) * max(0.02, st), y + 50 * k, 14 * k, T["accent"])
                    self.text((x0 + x1) / 2, y + 25 * k, f"Downloading… {st * 100:.0f}%", self.font(16 * k, True), T["text"], anchor="center")
                elif st == "restarting":
                    self.text(x0, y + 10 * k, "Installed. Restarting…", self.font(18 * k, True), T["good"])
                else:
                    self.button("up_install", x0, y, x0 + 320 * k, y + 54 * k, "INSTALL AND RESTART", self.install_update, "accent", 15)
                    if info["tag"] != self.cfg["update_skip"]:
                        self.button("up_skip", x0 + 340 * k, y, x0 + 560 * k, y + 54 * k, "SKIP THIS ONE",
                                    lambda: (self.set_cfg("update_skip", info["tag"]), self.show_toast("Won't remind you about this one")),
                                    "normal", 14)
                y += 80 * k
        elif st != "checking":
            self.text(x0, y, "Tap Check now to look for a new version.", self.font(16 * k), T["muted"])
            y += 40 * k
        if exe and os.path.exists(exe + ".old"):
            armed = self.is_armed("rollback")
            self.button("up_back", x0, self.H - 80 * k, x0 + 340 * k, self.H - 36 * k, "TAP AGAIN" if armed else "GO BACK TO THE LAST VERSION",
                        lambda: self.confirm("rollback", self.roll_back, "Tap again to go back to the version before the update"),
                        "danger" if armed else "normal", 13)
        self.text(x1, self.H - 58 * k, "Your notes, ratings and settings stay as they are.", self.font(12.5 * k), T["muted"], anchor="e")

    # ------------------------------------------------------------------ Storage
    def draw_storage(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        if self.library is None:
            return
        libs = [l for l in ({g["lib"] for g in self.library if g["lib"]} | ({self.steam["root"]} if self.steam else set()))]
        off = self.scroll.get("storage", 0)
        y = y0 - off
        colw = (x1 - x0 - 20 * k) / 2
        # drives
        dr = dc.drives(sorted(libs))
        for i, (label, path, used, total) in enumerate(dr):
            cx = x0 + (i % 2) * (colw + 20 * k)
            cy = y + (i // 2) * 132 * k
            self.rr(cx, cy, cx + colw, cy + 116 * k, 18 * k, mix(T["panel"], T["bg"], 0.1))
            self.text(cx + 20 * k, cy + 18 * k, label.upper(), self.font(12.5 * k, True), T["muted"])
            self.text(cx + 20 * k, cy + 40 * k, f"{dc.fmt_bytes(total - used)} free of {dc.fmt_bytes(total)}", self.font(20 * k, True), T["text"])
            frac = used / total if total else 0
            self.rr(cx + 20 * k, cy + 82 * k, cx + colw - 20 * k, cy + 96 * k, 7 * k, T["panel2"])
            self.rr(cx + 20 * k, cy + 82 * k, cx + 20 * k + (colw - 40 * k) * frac, cy + 96 * k, 7 * k,
                    T["danger"] if frac > 0.92 else T["warn"] if frac > 0.8 else T["accent"])
        y += max(1, math.ceil(len(dr) / 2)) * 132 * k + 6 * k
        # cleanup
        cl = self.cleanup
        if cl is None:
            self.button("scan", x0, y, x0 + 300 * k, y + 50 * k, "FIND THINGS TO CLEAN UP", self.scan_cleanup, "accent")
            self.text(x0 + 320 * k, y + 25 * k, "Shader caches and Proton folders that uninstalled games left behind",
                      self.font(14 * k), T["muted"], anchor="w")
            y += 70 * k
        elif cl == "scanning":
            self.text(x0, y + 14 * k, "Looking…", self.font(16 * k), T["muted"])
            y += 56 * k
        else:
            leftovers, caches = cl
            tot = sum(x["size"] for x in leftovers)
            self.text(x0, y, f"LEFTOVERS  ·  {dc.fmt_bytes(tot)}", self.font(13 * k, True), T["muted"])
            self.button("rescan", x1 - 150 * k, y - 8 * k, x1, y + 30 * k, "CHECK AGAIN", self.scan_cleanup, "normal", 13)
            y += 32 * k
            if not leftovers:
                self.text(x0, y, "All tidy: nothing left behind by uninstalled games.", self.font(15 * k), T["good"])
                y += 40 * k
            for i, it in enumerate(leftovers[:12]):
                y = self.cleanup_row(it, i, x0, y, x1, leftover=True)
            y += 10 * k
            self.text(x0, y, "SHADER CACHES OF INSTALLED GAMES", self.font(13 * k, True), T["muted"])
            y += 26 * k
            self.text(x0, y, "Safe to clear: Steam rebuilds them (the first minutes of a game may stutter while it does).",
                      self.font(13.5 * k), T["muted"])
            y += 28 * k
            for i, it in enumerate(caches[:12]):
                y = self.cleanup_row(it, 100 + i, x0, y, x1, leftover=False)
        y += 16 * k
        dups = dc.duplicates(self.library)
        if dups:
            self.text(x0, y, "INSTALLED TWICE", self.font(13 * k, True), T["muted"])
            y += 28 * k
            for i, grp in enumerate(dups[:6]):
                self.rr(x0, y, x1, y + 52 * k, 14 * k, mix(T["panel"], T["bg"], 0.1))
                self.text(x0 + 18 * k, y + 26 * k, grp[0]["name"], self.font(15 * k, True), T["text"], anchor="w", maxw=(x1 - x0) * 0.4)
                where = "  and  ".join(f"{g['source']}" + (f" ({dc.fmt_bytes(g['size'])})" if g["size"] else "") for g in grp)
                self.text(x0 + (x1 - x0) * 0.45, y + 26 * k, where + "  ·  you only need one", self.font(14 * k), T["warn"], anchor="w",
                          maxw=(x1 - x0) * 0.53)
                self.region(f"dup_{i}", x0, y, x1, y + 52 * k, lambda gid=grp[0]["id"]: self.open_game(gid))
                y += 60 * k
            y += 10 * k
        # biggest games
        self.text(x0, y, "BIGGEST GAMES", self.font(13 * k, True), T["muted"])
        y += 28 * k
        for g in sorted([g for g in self.library if g["size"]], key=lambda g: -g["size"])[:10]:
            self.rr(x0, y, x1, y + 52 * k, 14 * k, mix(T["panel"], T["bg"], 0.1))
            self.text(x0 + 18 * k, y + 26 * k, g["name"], self.font(15 * k, True), T["text"], anchor="w", maxw=(x1 - x0) * 0.5)
            self.text(x0 + (x1 - x0) * 0.55, y + 26 * k, f"{dc.fmt_bytes(g['size'])}  ·  last played {dc.ago(g['last'])}",
                      self.font(14 * k), T["muted"], anchor="w")
            self.region("big_" + g["id"], x0, y, x1, y + 52 * k, lambda gid=g["id"]: self.open_game(gid))
            y += 60 * k
        total_h = y + off - y0
        self.clamp_scroll("storage", total_h - (y1 - y0))
        self.region("st_scroll", x0, y0, x1, y1, None, scroll="storage")

    def cleanup_row(self, it, i, x0, y, x1, leftover):
        T, k = self.t, self.k
        g = next((g for g in self.library or [] if g["appid"] == it["appid"]), None)
        name = g["name"] if g else (it.get("name") or f"App {it['appid']}") + ("" if g else "  (not installed)")
        kind = "Shader cache" if it["kind"] == "shaders" else "Proton folder (may hold saves)"
        self.rr(x0, y, x1, y + 56 * k, 14 * k, mix(T["panel"], T["bg"], 0.1))
        self.text(x0 + 18 * k, y + 16 * k, name, self.font(15 * k, True), T["text"], maxw=(x1 - x0) * 0.5)
        self.text(x0 + 18 * k, y + 36 * k, f"{kind}  ·  {dc.fmt_bytes(it['size'])}", self.font(12.5 * k),
                  T["warn"] if it["kind"] == "prefix" else T["muted"])
        key = f"cl_{i}_{it['path']}"
        armed = self.is_armed(key)
        lab = "TAP AGAIN" if armed else ("TO TRASH" if leftover else "CLEAR")
        self.button(f"clr_{i}", x1 - 150 * k, y + 9 * k, x1 - 12 * k, y + 47 * k, lab,
                    lambda: self.confirm(key, lambda: self.trash_item(it), "Tap again to move it to the Trash"),
                    "danger" if armed else "normal", 13)
        return y + 64 * k

    def scan_cleanup(self):
        self.cleanup = "scanning"
        libs = sorted({g["lib"] for g in self.library or [] if g["lib"]} | ({self.steam["root"]} if self.steam else set()))
        games = [g for g in self.library or []]

        def work():
            try:
                res = dc.cleanup_scan(games, libs)
                for it in res[0][:20]:
                    it["name"] = dc.app_name(it["appid"])
            except Exception:
                res = ([], [])
            self.call(lambda: (setattr(self, "cleanup", res), self.redraw()))
        self.background(work)
        self.redraw()

    def trash_item(self, it):
        def work():
            ok = dc.trash(it["path"])

            def fin():
                if ok and isinstance(self.cleanup, tuple):
                    self.cleanup = tuple([x for x in lst if x["path"] != it["path"]] for lst in self.cleanup)
                self.show_toast(f"Moved to the Trash: {dc.fmt_bytes(it['size'])}" if ok else "Couldn't move it (in use?)")
            self.call(fin)
        self.background(work)

    # ------------------------------------------------------------------ System
    def draw_system(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        s = self.stats or {}
        b = s.get("batt") or {}
        u = "°F" if self.cfg["fahrenheit"] else "°C"
        tc = lambda v: f"{v * 9 / 5 + 32:.0f}{u}" if self.cfg["fahrenheit"] else f"{v:.0f}{u}"
        tiles = [
            ("BATTERY", f"{b.get('pct', '–')}%" if b else "–",
             (f"{b['status'].lower()}" + (f" · {b['watts']:.1f} W" if b.get("watts") else "") +
              (f" · {dc.fmt_duration(b['left'])} left" if b.get("left") else "")) if b else "No battery", "watts"),
            ("CPU", f"{s['cpu']:.0f}%" if s.get("cpu") is not None else "–", tc(s["cpu_temp"]) if s.get("cpu_temp") else "", "cpu"),
            ("GPU", f"{s['gpu']:.0f}%" if s.get("gpu") is not None else "–",
             " · ".join(x for x in (tc(s["gpu_temp"]) if s.get("gpu_temp") else "", f"{s['apu_watts']:.1f} W APU" if s.get("apu_watts") else "") if x),
             "gpu"),
            ("FAN", f"{s['fan']:.0f} rpm" if s.get("fan") is not None else "–", "", None),
            ("MEMORY", f"{s['mem'][0] / 2**30:.1f} GB" if s.get("mem") else "–", f"of {s['mem'][1] / 2**30:.0f} GB" if s.get("mem") else "", None),
            ("BATTERY HEALTH", f"{b['health']:.0f}%" if b.get("health") else "–",
             (f"{b['full_wh']:.1f} of {b['design_wh']:.1f} Wh" if b.get("full_wh") and b.get("design_wh") else "") +
             (f" · {b['cycles']:.0f} cycles" if b.get("cycles") else ""), None),
        ]
        cols, gap = 3, 18 * k
        tw = (x1 - x0 - gap * (cols - 1)) / cols
        th = (y1 - y0 - gap) / 2
        for i, (lab, big, sub, hist) in enumerate(tiles):
            r_, cn = divmod(i, cols)
            tx, ty = x0 + cn * (tw + gap), y0 + r_ * (th + gap)
            self.rr(tx, ty, tx + tw, ty + th, 20 * k, mix(T["panel"], T["bg"], 0.1))
            if lab == "MEMORY":
                self.button("sys_ram", tx + 22 * k, ty + th - 66 * k, tx + tw - 22 * k, ty + th - 22 * k, "FREE UP RAM", self.open_ram,
                            "accent", 15)
            self.text(tx + 22 * k, ty + 20 * k, lab, self.font(13 * k, True), T["muted"])
            self.text(tx + 22 * k, ty + 44 * k, big, self.font(40 * k, True), T["text"])
            self.text(tx + 22 * k, ty + 100 * k, sub, self.font(14.5 * k), T["muted"], maxw=tw - 44 * k)
            h = self.sensors.hist.get(hist) if hist else None
            if h and len(h) > 2:
                top = max(max(h), 1)
                if hist in ("cpu", "gpu"):
                    top = 100
                gx0, gx1, gy1 = tx + 22 * k, tx + tw - 22 * k, ty + th - 20 * k
                gh = th - 150 * k
                pts = []
                for j, v in enumerate(h):
                    pts += [gx0 + (gx1 - gx0) * j / max(1, len(h) - 1), gy1 - gh * min(1, v / top)]
                self.c.create_polygon(pts + [gx1, gy1, gx0, gy1], fill=mix(T["panel"], T["accent"], 0.22), outline="")
                self.c.create_line(*pts, fill=T["accent"], width=max(2, 2 * k))
        if s.get("uptime"):
            self.text(x0, y1 + 4 * k, f"Up for {dc.fmt_duration(s['uptime'])}", self.font(13 * k), T["muted"])

    # ------------------------------------------------------------------ Settings
    def draw_settings(self, x0, y0, x1, y1):
        T, k = self.t, self.k
        off = self.scroll.get("settings", 0)
        y = y0 - off
        y = self.setting_row(x0, y, x1, "Theme", f"{len(THEMES)} themes, {sum(1 for t in THEMES.values() if t.get('fx'))} of them animated",
                             f"{self.cfg['theme']}  ›", lambda: self.open_page("themes"), True)
        a, b = self.cfg["day_hours"]
        y = self.setting_row(x0, y, x1, "Day & night", f"Use {self.cfg['day_theme']} from {a}:00 to {b}:00 (pick it on the Themes page)",
                             "ON" if self.cfg["day_night"] else "OFF", lambda: self.set_cfg("day_night", not self.cfg["day_night"]),
                             self.cfg["day_night"])
        rows = [("animations", "Animated backgrounds", "Themes marked ✦ move gently. Off saves a little battery.", self.cfg["animations"]),
                ("fahrenheit", "Temperatures in °F", "System shows °C otherwise", self.cfg["fahrenheit"]),
                ("art_fetch", "Download missing covers", "From Steam's public image server", self.cfg["art_fetch"]),
                ("stores", "Games from Heroic and Lutris", "Epic, GOG and Amazon games installed with Heroic, and Lutris games",
                 self.cfg["stores"])]
        for key, title, sub, on in rows:
            y = self.setting_row(x0, y, x1, title, sub, "ON" if on else "OFF", lambda k_=key: self.set_cfg(k_, not self.cfg[k_]), on)
        starts = [t for t, _ in TABS[:4]]
        y = self.setting_row(x0, y, x1, "Open on", "The tab Vanta Deck starts on", dict(TABS)[self.cfg["start_tab"]].upper(),
                             lambda: self.set_cfg("start_tab", starts[(starts.index(self.cfg["start_tab"]) + 1) % len(starts)]
                                                  if self.cfg["start_tab"] in starts else "home"), True)
        sizes = [90, 100, 115, 130]
        y = self.setting_row(x0, y, x1, "Size of everything", "Bigger is easier to read on the TV", f"{self.cfg['ui_scale']}%",
                             lambda: self.set_cfg("ui_scale", sizes[(sizes.index(self.cfg["ui_scale"]) + 1) % len(sizes)]
                                                  if self.cfg["ui_scale"] in sizes else 100), True)
        up = self.update
        y = self.setting_row(x0, y, x1, "Updates", (f"Vanta Deck {up['version']} is ready to install" if up and up["newer"] else
                                                    f"You have {VERSION}" + (f"  ·  checked {dc.ago(self.cfg['update_last'])}"
                                                                             if self.cfg["update_last"] else "")),
                             "UPDATE  ›" if up and up["newer"] else "CHECK  ›", lambda: self.open_page("update"), bool(up and up["newer"]))
        exe = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
        y = self.setting_row(x0, y, x1, "Add Vanta Deck to Steam", "So it opens in Game Mode like a game (Desktop Mode)", "ADD",
                             lambda: self.show_toast("Added: find it under Non-Steam in Game Mode" if dc.add_to_steam(exe)
                                                     else "Use Steam › Add a Non-Steam Game in Desktop Mode"), True)
        self.text(x0, y + 10 * k, f"{APP} {VERSION}  ·  data in {dc.DATA}", self.font(13 * k), T["muted"])
        y += 40 * k
        self.clamp_scroll("settings", y + off - y0 - (y1 - y0))
        self.region("set_scroll", x0, y0, x1, y1, None, scroll="settings")

    def setting_row(self, x0, y, x1, title, sub, val, fn, on):
        T, k = self.t, self.k
        rid = "set_" + title
        self.rr(x0, y, x1, y + 70 * k, 16 * k, mix(T["panel"], T["bg"], 0.1))
        self.text(x0 + 20 * k, y + 16 * k, title, self.font(16 * k, True), T["text"])
        self.text(x0 + 20 * k, y + 40 * k, sub, self.font(13.5 * k), T["muted"])
        f = self.font(14 * k, True)
        w = f.measure(val) + 34 * k
        self.rr(x1 - 20 * k - w, y + 17 * k, x1 - 20 * k, y + 53 * k, 18 * k, T["accent"] if on else T["panel2"])
        self.text(x1 - 20 * k - w / 2, y + 35 * k, val, f, on_color(T["accent"]) if on else T["muted"], anchor="center")
        self.region(rid, x0, y, x1, y + 70 * k, fn)
        return y + 80 * k

    def set_theme(self, name):
        self.cfg["day_theme" if self.theme_slot == "day" and self.cfg["day_night"] else "theme"] = name
        self.fx = None
        self.imgs = {k_: v for k_, v in self.imgs.items() if k_[0] not in ("bd", "hero")}
        self.redraw()

    def set_tab(self, tid):
        self.tab = tid
        self.page = None
        self.hide_entry()
        self.focus = None
        if tid == "storage" and self.cleanup is None and self.library:
            self.scan_cleanup()
        self.redraw()

    # ------------------------------------------------------------------ animated backgrounds
    def fx_draw(self, W, H):
        kind = self.t.get("fx") if self.cfg["animations"] else None
        if not kind:
            self.fx = None
            return
        if not self.fx or self.fx["key"] != (kind, W, H, self.cfg["theme"]):
            rnd = random.Random(7)
            n = {"stars": 46, "petals": 26, "orbs": 5, "aurora": 4, "waves": 4, "glow": 0, "snow": 60, "embers": 34, "fireflies": 22,
                 "rain": 70, "bubbles": 26, "confetti": 40, "grid": 12, "scan": 1}.get(kind, 0)
            self.fx = {"key": (kind, W, H, self.cfg["theme"]), "kind": kind, "t": time.time(),
                       "p": [dict(x=rnd.random() * W, y=rnd.random() * H, r=rnd.random(), ph=rnd.random() * 6.3,
                                  v=0.4 + rnd.random()) for _ in range(n)]}
        T, k = self.t, self.k
        self.fx["ids"] = []
        for p in self.fx["p"]:
            if kind == "stars":
                r = (0.8 + p["r"] * 1.6) * k
                iid = self.c.create_rectangle(p["x"] - r, p["y"] - r, p["x"] + r, p["y"] + r, fill=mix(T["bg"], "#ffffff", 0.6), outline="")
            elif kind == "petals":
                r = (5 + p["r"] * 6) * k
                iid = self.c.create_oval(p["x"] - r, p["y"] - r * 0.6, p["x"] + r, p["y"] + r * 0.6, fill=mix(T["bg"], T["accent"], 0.5), outline="")
            elif kind == "snow":
                r = (1.2 + p["r"] * 2.6) * k
                iid = self.c.create_oval(p["x"] - r, p["y"] - r, p["x"] + r, p["y"] + r, fill=mix(T["bg"], "#ffffff", 0.35 + p["r"] * 0.4),
                                         outline="")
            elif kind == "embers":
                r = (1.2 + p["r"] * 2.2) * k
                iid = self.c.create_oval(p["x"] - r, p["y"] - r, p["x"] + r, p["y"] + r,
                                         fill=mix(T["bg"], T["accent"] if p["r"] > 0.4 else T["accent2"], 0.55 + p["r"] * 0.4), outline="")
            elif kind == "fireflies":
                spr = self.orb(int((14 + p["r"] * 12) * k), T["accent"] if p["r"] > 0.3 else T["accent2"], strong=True)
                iid = self.c.create_image(p["x"], p["y"], image=spr) if spr else None
            elif kind == "rain":
                ln = (14 + p["r"] * 14) * k
                iid = self.c.create_line(p["x"], p["y"], p["x"] - ln * 0.18, p["y"] + ln, fill=mix(T["bg"], T["accent2"], 0.25 + p["r"] * 0.3),
                                         width=max(1, 1.2 * k))
            elif kind == "bubbles":
                r = (4 + p["r"] * 10) * k
                iid = self.c.create_oval(p["x"] - r, p["y"] - r, p["x"] + r, p["y"] + r, outline=mix(T["bg"], T["accent2"], 0.45),
                                         width=max(1, 1.4 * k))
            elif kind == "confetti":
                w, h = (4 + p["r"] * 4) * k, (7 + p["r"] * 5) * k
                col = (T["accent"], T["accent2"], T["warn"], T["good"], T["danger"])[int(p["ph"] * 10) % 5]
                iid = self.c.create_rectangle(p["x"], p["y"], p["x"] + w, p["y"] + h, fill=mix(T["bg"], col, 0.7), outline="")
            elif kind == "grid":
                hz = H * 0.58
                if p is self.fx["p"][0]:  # the fixed rays, drawn once with the first line
                    for i in range(-8, 9):
                        rid_ = self.c.create_line(W / 2 + i * W * 0.02, hz, W / 2 + i * W * 0.16, H, fill=mix(T["bg"], T["accent"], 0.22))
                        self.c.tag_lower(rid_)
                f_ = (self.fx["p"].index(p) / len(self.fx["p"]))
                p["f"] = f_
                y_ = hz + (H - hz) * f_ * f_
                p["x"], p["y"] = 0, y_
                iid = self.c.create_line(0, y_, W, y_, fill=mix(T["bg"], T["accent"], 0.3))
            elif kind == "scan":
                p["y"] = -40 * k
                iid = self.c.create_rectangle(0, p["y"], W, p["y"] + 70 * k, fill=mix(T["bg"], T["accent"], 0.07), outline="")
            else:
                spr = self.orb(int((140 + p["r"] * 120) * k), T["accent"] if p["r"] > 0.5 else T["accent2"])
                iid = self.c.create_image(p["x"], p["y"], image=spr) if spr else None
            if iid:
                self.c.tag_lower(iid)
                self.fx["ids"].append((iid, p))
        self.c.tag_lower("backdrop")

    def orb(self, R, col, strong=False):
        key = ("orb", R, col, strong)
        if key not in self.imgs:
            n = max(2, R * 2)
            m = Image.new("L", (n, n), 0)
            ImageDraw.Draw(m).ellipse((n * 0.2, n * 0.2, n * 0.8, n * 0.8), fill=230 if strong else 90)
            m = m.filter(ImageFilter.GaussianBlur(n * 0.12))
            im = Image.new("RGBA", (n, n), tuple(int(col[i:i + 2], 16) for i in (1, 3, 5)) + (0,))
            im.putalpha(m)
            self.imgs[key] = ImageTk.PhotoImage(im)
        return self.imgs[key]

    def fx_loop(self):
        delay = 500
        fx = self.fx
        if fx and fx.get("ids") and self.cfg["animations"] and not self.running:
            t0 = time.perf_counter()
            now = time.time()
            dt = min(1.0, now - fx["t"])
            fx["t"] = now
            W, H = self.W, self.H
            k = self.k
            for iid, p in fx["ids"]:
                if fx["kind"] == "stars":
                    dx, dy = -p["v"] * 18 * k * dt, 0
                    p["x"] += dx
                    if p["x"] < -5:
                        p["x"] += W + 10
                        dx += W + 10
                elif fx["kind"] == "petals":
                    dy = p["v"] * 30 * k * dt
                    dx = math.sin(now * 0.8 + p["ph"]) * 14 * k * dt + 10 * k * dt
                    p["x"] += dx
                    p["y"] += dy
                    if p["y"] > H + 20:
                        p["y"] -= H + 40
                        dy -= H + 40
                    if p["x"] > W + 20:
                        p["x"] -= W + 40
                        dx -= W + 40
                elif fx["kind"] in ("snow", "embers"):
                    up = fx["kind"] == "embers"
                    dy = (-1 if up else 1) * p["v"] * (26 if up else 22) * k * dt
                    dx = math.sin(now * (1.1 if up else 0.5) + p["ph"]) * (12 if up else 9) * k * dt
                    p["x"] += dx
                    p["y"] += dy
                    if not up and p["y"] > H + 10:
                        p["y"] -= H + 20
                        dy -= H + 20
                    elif up and p["y"] < -10:
                        p["y"] += H + 20
                        dy += H + 20
                elif fx["kind"] in ("rain", "confetti", "bubbles"):
                    sp = {"rain": 420, "confetti": 40, "bubbles": -30}[fx["kind"]]
                    dy = sp * (0.6 + p["v"] * 0.5) * k * dt
                    dx = (-dy * 0.18 if fx["kind"] == "rain" else math.sin(now * 1.3 + p["ph"]) * 16 * k * dt)
                    p["x"] += dx
                    p["y"] += dy
                    if dy > 0 and p["y"] > H + 30:
                        p["y"] -= H + 60
                        dy -= H + 60
                    elif dy < 0 and p["y"] < -30:
                        p["y"] += H + 60
                        dy += H + 60
                    if p["x"] < -30:
                        p["x"] += W + 60
                        dx += W + 60
                elif fx["kind"] == "grid":
                    p["f"] = (p["f"] + 0.05 * dt) % 1.0
                    hz = H * 0.58
                    ny = hz + (H - hz) * p["f"] * p["f"]
                    dx, dy = 0, ny - p["y"]
                    p["y"] = ny
                elif fx["kind"] == "scan":
                    dx, dy = 0, 90 * k * dt
                    p["y"] += dy
                    if p["y"] > H:
                        p["y"] -= H + 80 * k
                        dy -= H + 80 * k
                elif fx["kind"] == "fireflies":
                    a = now * 0.35 * p["v"] + p["ph"]
                    nx = p.setdefault("cx", p["x"]) + math.sin(a) * 70 * k + math.sin(a * 2.3) * 20 * k
                    ny = p.setdefault("cy", p["y"]) + math.cos(a * 0.9) * 50 * k
                    dx, dy = nx - p["x"], ny - p["y"]
                    p["x"], p["y"] = nx, ny
                else:
                    a = now * 0.12 * p["v"] + p["ph"]
                    nx = p.setdefault("cx", p["x"]) + math.sin(a) * W * 0.12
                    ny = p.setdefault("cy", p["y"]) + math.cos(a * 0.8) * H * 0.1
                    dx, dy = nx - p["x"], ny - p["y"]
                    p["x"], p["y"] = nx, ny
                self.c.move(iid, dx, dy)
            self.root.update_idletasks()
            cost = time.perf_counter() - t0
            self.fx_cost = self.fx_cost * 0.7 + cost * 0.3
            delay = int(max(1 / 30 - cost, self.fx_cost * 0.8, 0.004) * 1000)
        self.root.after(max(4, delay), self.fx_loop)

    # ------------------------------------------------------------------ input
    def hit(self, x, y, scroll=False):
        for r in reversed(self.regions):
            if r["x0"] <= x <= r["x1"] and r["y0"] <= y <= r["y1"] and (bool(r["scroll"]) == scroll):
                return r
        return None

    def on_press(self, e):
        self.focus_visible = False
        r = self.hit(e.x, e.y)
        sr = self.hit(e.x, e.y, scroll=True)
        self.drag = {"x": e.x, "y": e.y, "r": r, "sr": sr, "moved": False, "off": self.scroll.get(sr["scroll"], 0) if sr else 0}
        if r:
            self.pressed = r["id"]
            self.redraw()

    def on_drag(self, e):
        d = self.drag
        if not d:
            return
        if abs(e.y - d["y"]) > 12 * self.k:
            d["moved"] = True
            if self.pressed:
                self.pressed = None
        if d["moved"] and d["sr"]:
            self.scroll[d["sr"]["scroll"]] = d["off"] - (e.y - d["y"])
            self.redraw()

    def on_release(self, e):
        d, self.drag = self.drag, None
        self.pressed = None
        if d and not d["moved"] and d["r"]:
            r = self.hit(e.x, e.y)
            if r and r["id"] == d["r"]["id"] and r["tap"]:
                r["tap"]()
                return
        self.redraw()

    def on_key(self, e):
        if self.entry and e.widget is self.entry:
            return
        ks = e.keysym
        m = {"Up": "up", "Down": "down", "Left": "left", "Right": "right", "Return": "a", "KP_Enter": "a", "space": "a",
             "Escape": "b", "BackSpace": "b", "q": "lb", "e": "rb", "Prior": "lb", "Next": "rb", "x": "x", "y": "y", "F11": "full"}
        b = m.get(ks)
        if b == "full":
            self.root.attributes("-fullscreen", not self.root.attributes("-fullscreen"))
        elif b:
            self.on_pad(b)

    def default_focus(self):
        if self.page:
            return {"game": "gp_play", "shot": "sv_next", "ram": "ram_auto", "goal": "goal_0", "remote": "rm_toggle",
                    "startup": "su_0", "pad": "pg_back", "backup": "bk_make", "themes": "th_" + self.cfg["theme"],
                    "update": "up_install" if self.update and self.update["newer"] else "up_check"}.get(self.page[0])
        return {"home": "home_play", "library": next((r["id"] for r in self.regions if r["id"].startswith("g_")), None),
                "play": "pr_" + self.cfg["play_range"], "shots": next((r["id"] for r in self.regions if r["id"].startswith("sh_")), None),
                "storage": "scan", "system": "sys_ram", "tools": "tool_boost", "settings": "set_Theme"}.get(self.tab)

    def on_pad(self, b):
        if self.entry:
            if b == "b":
                self.hide_entry()
            return
        if self.page and self.page[0] == "pad":
            if b == "b" and getattr(self, "_pad_b", 0) > time.time() - 1.5:
                self.close_page()
            else:
                self._pad_b = time.time() if b == "b" else 0
                if b == "b":
                    self.show_toast("Press B again to leave")
            return
        if self.page and self.page[0] == "shot" and b in ("left", "right", "lb", "rb"):
            self.step_shot(-1 if b in ("left", "lb") else 1)
            return
        if not self.focus_visible:
            self.focus_visible = True
            self.focus = self.focus or self.default_focus()
            if b in ("up", "down", "left", "right", "a"):
                self.redraw()
                return
        if b in ("lb", "rb"):
            ids = [t for t, _ in TABS]
            i = ids.index(self.tab)
            self.set_tab(ids[(i + (1 if b == "rb" else -1)) % len(ids)])
            self.focus = self.default_focus()
            self.redraw()
        elif b == "b":
            if self.page:
                self.close_page()
            elif self.tab != "home":
                self.set_tab("home")
        elif b == "a":
            r = next((r for r in self.regions if r["id"] == self.focus), None)
            if r and r["tap"]:
                r["tap"]()
        elif b == "x":
            g = (self.game(self.page[1]) if self.page[0] == "game" else None) if self.page else (self.game(self.focus[2:]) if self.focus and self.focus.startswith("g_")
                                                          else self.home_game() if self.tab == "home" else None)
            if g:
                self.play(g)
        elif b == "y" and self.focus and self.focus.startswith(("g_", "home_g_")):
            gid = self.focus[len("home_g_"):] if self.focus.startswith("home_g_") else self.focus[2:]
            self.toggle("favorites", gid)
        elif b in ("up", "down", "left", "right"):
            self.move_focus(b)

    def move_focus(self, d):
        cur = next((r for r in self.regions if r["id"] == self.focus), None)
        cands = [r for r in self.regions if r["tap"] and r["id"] != self.focus]
        if not cur:
            self.focus = self.default_focus() or (cands[0]["id"] if cands else None)
            return self.redraw()
        cx, cy = (cur["x0"] + cur["x1"]) / 2, (cur["y0"] + cur["y1"]) / 2
        best, bs = None, None
        for r in cands:
            rx, ry = (r["x0"] + r["x1"]) / 2, (r["y0"] + r["y1"]) / 2
            dx, dy = rx - cx, ry - cy
            if d == "up" and dy >= -5 or d == "down" and dy <= 5 or d == "left" and dx >= -5 or d == "right" and dx <= 5:
                continue
            main, side = (abs(dy), abs(dx)) if d in ("up", "down") else (abs(dx), abs(dy))
            score = main + side * 2.2
            if bs is None or score < bs:
                best, bs = r, score
        if best:
            self.focus = best["id"]
            self.reveal(best)
        self.redraw()

    def reveal(self, r):
        """Scroll so the focused item is on screen."""
        key = ({"game": "game", "ram": "ram", "themes": "themes"}.get(self.page[0]) if self.page else
               {"library": "lib", "storage": "storage", "settings": "settings", "play": "play", "shots": "shots"}.get(self.tab))
        if not key:
            return
        top, bottom = 150 * self.k, self.H - 70 * self.k
        if r["y1"] > bottom:
            self.scroll[key] = self.scroll.get(key, 0) + (r["y1"] - bottom) + 20 * self.k
        elif r["y0"] < top:
            self.scroll[key] = max(0, self.scroll.get(key, 0) - (top - r["y0"]) - 20 * self.k)


def main():
    app = App()
    if os.environ.get("VANTA_TAB"):  # tests
        app.root.after(1500, lambda: app.set_tab(os.environ["VANTA_TAB"]))
    if os.environ.get("VANTA_PAGE"):  # tests: open a Tools page
        def _pg():
            pg = os.environ["VANTA_PAGE"]
            if pg == "ram":
                app.open_ram()
            elif pg == "update":
                app.open_page("update")
                app.check_update()
            else:
                if pg == "startup":
                    app.load_startup()
                if pg == "backup":
                    app.load_backups()
                app.open_page(pg)
        app.root.after(2500, _pg)
    if os.environ.get("VANTA_OPEN"):
        app.root.after(2500, lambda: app.open_game(os.environ["VANTA_OPEN"]))
    if os.environ.get("VANTA_PADSEQ"):
        for i, b in enumerate(os.environ["VANTA_PADSEQ"].split(",")):
            app.root.after(3000 + i * 250, lambda b_=b: app.on_pad(b_))
    if os.environ.get("VANTA_SHOT"):  # tests: draw, save a screenshot request marker and quit
        app.root.after(int(os.environ.get("VANTA_SHOT_WAIT", "4000")), lambda: (print("READY", flush=True)))
    app.root.mainloop()


if __name__ == "__main__":
    main()
