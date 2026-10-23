import subprocess, sys, os
import os
WORK=os.environ.get("MLCI_WORK", os.getcwd())  # set MLCI_WORK to the workspace root
TREE=WORK+"/tor-stock"
M=TREE+"/src/core/mainloop/mainloop.c"
C=TREE+"/src/core/mainloop/connection.c"
# (id, file, old, new, desc)
muts=[
 ("M1_array_reset_skip", M,
  "  /* connection_free_() checks this to confirm conn has left the array. */\n  conn->conn_array_index = -1;\n",
  "  /* MUTANT M1: skip reset */\n", "connection_remove: do not reset conn_array_index"),
 ("M2_array_moved_off", M,
  "  tmp = smartlist_get(connection_array, current_index);\n  tmp->conn_array_index = current_index;\n",
  "  tmp = smartlist_get(connection_array, current_index);\n  tmp->conn_array_index = current_index + 1; /* MUTANT M2 */\n",
  "connection_remove: wrong moved-element array index"),
 ("M3_close_add_zero", M,
  "  conn->closeable_conn_index = smartlist_len(closeable_connection_lst);\n",
  "  conn->closeable_conn_index = 0; /* MUTANT M3 */\n",
  "add_connection_to_closeable_list: wrong index on add"),
 ("M4_close_reset_skip", M,
  "  smartlist_del(closeable_connection_lst, idx);\n  conn->closeable_conn_index = -1;\n",
  "  smartlist_del(closeable_connection_lst, idx);\n  /* MUTANT M4: skip reset */\n",
  "remove_from_closeable_list: do not reset index"),
 ("M5_close_moved_off", M,
  "    moved->closeable_conn_index = idx;\n",
  "    moved->closeable_conn_index = idx + 1; /* MUTANT M5 */\n",
  "remove_from_closeable_list: wrong moved-element index"),
 ("M6_active_add_zero", M,
  "    conn->active_linked_conn_index =\n      smartlist_len(active_linked_connection_lst);\n",
  "    conn->active_linked_conn_index = 0; /* MUTANT M6 */\n",
  "start_reading_from_linked_conn: wrong index on add"),
 ("M7_active_reset_skip", M,
  "  smartlist_del(active_linked_connection_lst, idx);\n  conn->active_linked_conn_index = -1;\n",
  "  smartlist_del(active_linked_connection_lst, idx);\n  /* MUTANT M7: skip reset */\n",
  "remove_from_active_linked_list: do not reset index"),
 ("M8_active_flag_skip", M,
  "  conn->active_linked_conn_index = -1;\n  conn->active_on_link = 0;\n",
  "  conn->active_linked_conn_index = -1;\n  /* MUTANT M8: skip active_on_link=0 */\n",
  "remove_from_active_linked_list: do not clear active_on_link"),
 ("M9_active_moved_off", M,
  "    moved->active_linked_conn_index = idx;\n",
  "    moved->active_linked_conn_index = idx + 1; /* MUTANT M9 */\n",
  "remove_from_active_linked_list: wrong moved-element index"),
]
def read(f): return open(f).read()
def write(f,s): open(f,"w").write(s)
# sanity: unique
for mid,f,old,new,desc in muts:
    s=read(f); n=s.count(old)
    if n!=1: print("NONUNIQUE %s count=%d"%(mid,n)); sys.exit(1)
results=[]
for mid,f,old,new,desc in muts:
    orig=read(f); write(f, orig.replace(old,new,1))
    try:
        cmd=("make -j16 src/test/test >/tmp/mk.log 2>&1; mk=$?; "
             "if [ $mk != 0 ]; then echo BUILD_FAIL; else "
             "./src/test/test 'mainloop/..' >/tmp/mt.log 2>&1; echo TEST_rc=$?; fi")
        out=subprocess.run(["bash",WORK+"/scripts/dev.sh","tor-stock",cmd],
                           capture_output=True,text=True,timeout=1800).stdout
    finally:
        write(f,orig)
    status="?"
    if "BUILD_FAIL" in out: status="KILLED(build)"
    elif "TEST_rc=0" in out: status="SURVIVED"
    elif "TEST_rc=" in out: status="KILLED(test)"
    else: status="ERROR:"+out[-200:]
    print("%-22s %-12s %s"%(mid,status,desc)); results.append((mid,status,desc))
    sys.stdout.flush()
killed=sum(1 for _,s,_ in results if s.startswith("KILLED"))
print("\n%d/%d mutants killed"%(killed,len(results)))
import json; json.dump([{"id":m,"status":s,"desc":d} for m,s,d in results],
                       open(WORK+"/results/mutation.json","w"),indent=1)
