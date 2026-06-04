import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
css = open("static/research_new.css","r",encoding="utf-8").read().replace(chr(65279),"")
