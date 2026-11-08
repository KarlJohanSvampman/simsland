# Flow map

The page that shows every background job and what sets it off, drawn from `core/flow.py`:

```bash
python tools/flow_map/facts.py /tmp/facts.json
```

```bash
python tools/flow_map/build.py /tmp/facts.json tools/flow_map/template.html /tmp/simsland-event-flow.html
```

`facts.py` reads the job table and scans the code for what each job calls, what it emits and who listens.
`build.py` renders the diagrams (Mermaid) and tables into the template.
