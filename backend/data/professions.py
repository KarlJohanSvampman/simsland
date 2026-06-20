FIELDS_OF_STUDY = ["computer_science", "medicine", "law", "education", "engineering", "business", "psychology"]
PROFESSIONS = [
 {"id":"doctor","title":"Doctor","degree_required":"medicine","hourly_wage":60,"tags":["health","science","high_status"]},
 {"id":"lawyer","title":"Lawyer","degree_required":"law","hourly_wage":50,"tags":["law","argument","high_status"]},
 {"id":"software_engineer","title":"Software Engineer","degree_required":"computer_science","hourly_wage":42,"tags":["tech","logic"]},
 {"id":"teacher","title":"Teacher","degree_required":"education","hourly_wage":28,"tags":["education","social"]},
 {"id":"engineer","title":"Engineer","degree_required":"engineering","hourly_wage":40,"tags":["engineering","technical"]},
 {"id":"accountant","title":"Accountant","degree_required":"business","hourly_wage":32,"tags":["money","office"]},
 {"id":"retail_worker","title":"Retail Worker","degree_required":None,"hourly_wage":15,"tags":["service","store"]},
 {"id":"delivery_driver","title":"Delivery Driver","degree_required":None,"hourly_wage":18,"tags":["transport","traffic"]},
 {"id":"construction_worker","title":"Construction Worker","degree_required":None,"hourly_wage":24,"tags":["manual","physical"]},
 {"id":"cleaner","title":"Cleaner","degree_required":None,"hourly_wage":14,"tags":["manual","service"]},
 {"id":"barista","title":"Barista","degree_required":None,"hourly_wage":16,"tags":["cafe","social"]},
 {"id":"security_guard","title":"Security Guard","degree_required":None,"hourly_wage":19,"tags":["security","crime"]},
]
def get_profession(pid): return next((p for p in PROFESSIONS if p["id"] == pid), None)
