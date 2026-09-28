.PHONY: list test labs ui gate mcp clean
list:  ; python run_lab.py --list
test:  ; python -m unittest discover -s tests -t .
labs:  ; python run_lab.py all
ui:    ; streamlit run app/streamlit_app.py
gate:  ; python run_lab.py 27 --strict true
mcp:   ; npx @modelcontextprotocol/inspector python -m forge.mcp_server
clean: ; rm -rf runs/* .forge **/__pycache__
