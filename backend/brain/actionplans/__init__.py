"""
brain/actionplans -- needs, wants and expectations drive intentions; intentions are satisfied through ActionPlans.

    Drive        a need / want / expectation with a level and a threshold      (behaviour.json "drives")
    Intention    one per drive; holds plans in preference order + a scout plan ("intentions")
    ActionPlan   a graph: nodes (gate, decision, step, action, wait, plan, end) wired by their named outputs, with
                 named entry points that receive variables ("plans")
    Requirement  a yes/no statement a resolver answers from the world; characters hold beliefs about it
                 ("requirements")

store.py loads/saves simulations/<sim>/behaviour.json; checker.py proves every path; runner.py runs attempts on a
character. See the design doc "Intentions and ActionPlans".
"""
