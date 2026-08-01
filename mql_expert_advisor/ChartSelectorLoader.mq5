//+------------------------------------------------------------------+
//|                                         ChartSelectorLoader.mq5  |
//|                                         Infynite Solutions        |
//|  Expert Advisor: reset charts to the app's filtered watchlist,   |
//|  each opened on M1 with the new_me indicator template.           |
//|                                                                   |
//|  Setup (once):                                                    |
//|    1. Compile this file in MetaEditor (F7)                        |
//|    2. Navigator > Expert Advisors > new_me > ChartSelectorLoader  |
//|    3. Drag it onto ANY one chart and leave it running             |
//|                                                                   |
//|  On start / on each Python request:                               |
//|    close every other chart, then open ONLY the filtered symbol    |
//|    list from the app (enabled index classes). Never open the      |
//|    full unfiltered Market Watch on reload.                        |
//+------------------------------------------------------------------+
#property copyright   "Infynite Solutions"
#property version     "1.30"
#property description "Closes open charts, then opens enabled-class watchlist charts with new_me"
#property strict

#define REQUEST_FILE   "chart_selector\\open_charts.request"
#define STATUS_FILE    "chart_selector\\open_charts.status"
#define HEARTBEAT_FILE "chart_selector\\loader.heartbeat"
#define DESIRED_FILE   "chart_selector\\desired_symbols.list"
#define DEFAULT_TPL    "chart_selector_new_me.tpl"
#define POLL_SECONDS   1

bool g_startup_done = false;

//+------------------------------------------------------------------+
void WriteHeartbeat()
  {
   FolderCreate("chart_selector");
   int h = FileOpen(HEARTBEAT_FILE, FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h == INVALID_HANDLE)
      return;
   FileWriteString(h, "alive=1\n");
   FileWriteString(h, "symbol=" + _Symbol + "\n");
   FileWriteString(h, "chart_id=" + IntegerToString(ChartID()) + "\n");
   FileWriteString(h, "ts=" + TimeToString(TimeLocal(), TIME_DATE|TIME_SECONDS) + "\n");
   FileWriteString(h, "epoch=" + IntegerToString((int)TimeLocal()) + "\n");
   FileClose(h);
  }

//+------------------------------------------------------------------+
string ReadAll(const string path)
  {
   int h = FileOpen(path, FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(h == INVALID_HANDLE)
      return "";
   string out = "";
   while(!FileIsEnding(h))
      out += FileReadString(h) + "\n";
   FileClose(h);
   return out;
  }

//+------------------------------------------------------------------+
string KvGet(const string body, const string key, const string fallback = "")
  {
   string prefix = key + "=";
   int start = 0;
   while(start >= 0 && start < StringLen(body))
     {
      int nl = StringFind(body, "\n", start);
      if(nl < 0)
         nl = StringLen(body);
      string line = StringSubstr(body, start, nl - start);
      StringTrimLeft(line);
      StringTrimRight(line);
      if(StringFind(line, prefix) == 0)
         return StringSubstr(line, StringLen(prefix));
      start = nl + 1;
     }
   return fallback;
  }

//+------------------------------------------------------------------+
ENUM_TIMEFRAMES ParseTimeframe(const string tf)
  {
   if(tf == "M1")  return PERIOD_M1;
   if(tf == "M5")  return PERIOD_M5;
   if(tf == "M15") return PERIOD_M15;
   if(tf == "M30") return PERIOD_M30;
   if(tf == "H1")  return PERIOD_H1;
   return PERIOD_M1;
  }

//+------------------------------------------------------------------+
void WriteStatus(const int opened, const int updated, const int closed,
                 const int skipped, const string error)
  {
   FolderCreate("chart_selector");
   int h = FileOpen(STATUS_FILE, FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h == INVALID_HANDLE)
      return;
   FileWriteString(h, "ok=" + IntegerToString(error == "" ? 1 : 0) + "\n");
   FileWriteString(h, "opened=" + IntegerToString(opened) + "\n");
   FileWriteString(h, "updated=" + IntegerToString(updated) + "\n");
   FileWriteString(h, "closed=" + IntegerToString(closed) + "\n");
   FileWriteString(h, "skipped=" + IntegerToString(skipped) + "\n");
   FileWriteString(h, "error=" + error + "\n");
   FileWriteString(h, "ts=" + TimeToString(TimeLocal(), TIME_DATE|TIME_SECONDS) + "\n");
   FileClose(h);
  }

//+------------------------------------------------------------------+
int CloseAllChartsExceptHost(const long host_chart)
  {
   int closed = 0;
   // Multiple passes — ChartClose is async and the list shifts as we go.
   for(int pass = 0; pass < 5; pass++)
     {
      bool any = false;
      long id = ChartFirst();
      while(id >= 0)
        {
         long next = ChartNext(id);
         if(id != host_chart)
           {
            if(ChartClose(id))
              {
               closed++;
               any = true;
              }
           }
         id = next;
        }
      if(!any)
         break;
      Sleep(150);
     }
   return closed;
  }

//+------------------------------------------------------------------+
void CollectMarketWatchSymbols(string &desired[])
  {
   ArrayResize(desired, 0);
   int total = SymbolsTotal(true); // Market Watch only
   for(int i = 0; i < total; i++)
     {
      string sym = SymbolName(i, true);
      if(sym == "" || sym == NULL)
         continue;
      int sz = ArraySize(desired);
      ArrayResize(desired, sz + 1);
      desired[sz] = sym;
     }
  }

//+------------------------------------------------------------------+
void ParseSymbolsCsv(const string symbols_csv, string &desired[])
  {
   ArrayResize(desired, 0);
   if(symbols_csv == "")
      return;
   string parts[];
   int n = StringSplit(symbols_csv, '|', parts);
   for(int i = 0; i < n; i++)
     {
      string sym = parts[i];
      StringTrimLeft(sym);
      StringTrimRight(sym);
      if(sym == "" || sym == "*")
         continue;
      int sz = ArraySize(desired);
      ArrayResize(desired, sz + 1);
      desired[sz] = sym;
     }
  }

//+------------------------------------------------------------------+
void SaveDesiredSymbols(string &desired[])
  {
   FolderCreate("chart_selector");
   int h = FileOpen(DESIRED_FILE, FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(h == INVALID_HANDLE)
      return;
   for(int i = 0; i < ArraySize(desired); i++)
     {
      if(desired[i] == "")
         continue;
      FileWriteString(h, desired[i] + "\n");
     }
   FileClose(h);
  }

//+------------------------------------------------------------------+
bool LoadDesiredSymbolsFile(string &desired[])
  {
   ArrayResize(desired, 0);
   if(!FileIsExist(DESIRED_FILE))
      return false;
   string body = ReadAll(DESIRED_FILE);
   if(body == "")
      return false;

   int start = 0;
   while(start >= 0 && start < StringLen(body))
     {
      int nl = StringFind(body, "\n", start);
      if(nl < 0)
         nl = StringLen(body);
      string line = StringSubstr(body, start, nl - start);
      StringTrimLeft(line);
      StringTrimRight(line);
      if(line != "" && StringFind(line, "=") < 0)
        {
         int sz = ArraySize(desired);
         ArrayResize(desired, sz + 1);
         desired[sz] = line;
        }
      start = nl + 1;
     }
   return ArraySize(desired) > 0;
  }

//+------------------------------------------------------------------+
void RebuildCharts(string &desired[], const ENUM_TIMEFRAMES tf, const string tpl)
  {
   long host_chart = ChartID();
   int closed = CloseAllChartsExceptHost(host_chart);
   Sleep(300);

   int opened = 0, skipped = 0;
   string err = "";

   for(int i = 0; i < ArraySize(desired); i++)
     {
      string sym = desired[i];
      if(!SymbolSelect(sym, true))
        {
         skipped++;
         continue;
        }

      // Always open a fresh chart with indicators. The host chart (this EA)
      // is kept separately as the controller and is never templated.
      long chart_id = ChartOpen(sym, tf);
      if(chart_id <= 0)
        {
         skipped++;
         continue;
        }
      Sleep(200);

      if(!ChartApplyTemplate(chart_id, tpl))
        {
         err = "ChartApplyTemplate failed err=" + IntegerToString(GetLastError())
               + " tpl=" + tpl + " symbol=" + sym;
        }
      ChartRedraw(chart_id);
      opened++;
      Sleep(80);
     }

   WriteStatus(opened, 0, closed, skipped, err);
   Comment(StringFormat(
      "ChartSelectorLoader ON — closed %d, opened %d enabled-class chart(s)",
      closed, opened));
   PrintFormat("ChartSelectorLoader: closed=%d opened=%d skipped=%d err=%s",
               closed, opened, skipped, err);
  }

//+------------------------------------------------------------------+
void ProcessRequest()
  {
   if(!FileIsExist(REQUEST_FILE))
      return;

   string body = ReadAll(REQUEST_FILE);
   FileDelete(REQUEST_FILE);
   if(body == "")
     {
      WriteStatus(0, 0, 0, 0, "empty request");
      return;
     }

   string symbols_csv = KvGet(body, "symbols");
   string tpl         = KvGet(body, "template", DEFAULT_TPL);
   string tf_name     = KvGet(body, "timeframe", "M1");
   string source      = KvGet(body, "source", "symbols"); // symbols | market_watch
   ENUM_TIMEFRAMES tf = ParseTimeframe(tf_name);

   string desired[];
   // Only explicit source=market_watch may open the full MW set.
   // Empty symbols with source=symbols must NOT fall back to MW (that
   // reopened Boom/Crash/Step after the user disabled those classes).
   if(source == "market_watch")
      CollectMarketWatchSymbols(desired);
   else
      ParseSymbolsCsv(symbols_csv, desired);

   if(ArraySize(desired) == 0)
     {
      int closed = CloseAllChartsExceptHost(ChartID());
      WriteStatus(0, 0, closed, 0, "no symbols in filtered request");
      Comment("ChartSelectorLoader ON — filtered list empty");
      return;
     }

   SaveDesiredSymbols(desired);
   RebuildCharts(desired, tf, tpl);
  }

//+------------------------------------------------------------------+
void StartupResetFromDesiredList()
  {
   string desired[];
   if(LoadDesiredSymbolsFile(desired))
     {
      PrintFormat("ChartSelectorLoader: startup from desired_symbols.list (%d symbols)",
                  ArraySize(desired));
      RebuildCharts(desired, PERIOD_M1, DEFAULT_TPL);
      return;
     }

   // Do NOT open full Market Watch — it often still contains disabled classes
   // locked by leftover charts. Wait for the app to write a filtered list.
   Comment("ChartSelectorLoader ON — waiting for filtered symbol list from app");
   Print("ChartSelectorLoader: no desired_symbols.list — not opening Market Watch");
   WriteStatus(0, 0, 0, 0, "waiting for filtered desired symbols");
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   FolderCreate("chart_selector");
   g_startup_done = false;
   Comment("ChartSelectorLoader ON — loading filtered watchlist...");
   Print("ChartSelectorLoader EA started on ", _Symbol, " — filtered startup");
   // Short delay so the host chart finishes attaching before we close others.
   EventSetMillisecondTimer(500);
   return INIT_SUCCEEDED;
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   Comment("");
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   WriteHeartbeat();
   // First timer fire after attach: prefer a pending Python request (exact
   // enabled-class list). Else reopen the last filtered desired list.
   // Never fall back to unfiltered Market Watch on reload.
   if(!g_startup_done)
     {
      g_startup_done = true;
      EventKillTimer();
      EventSetTimer(POLL_SECONDS);
      if(FileIsExist(REQUEST_FILE))
         ProcessRequest();
      else
         StartupResetFromDesiredList();
      return;
     }
   ProcessRequest();
  }

//+------------------------------------------------------------------+
void OnTick()
  {
  }
//+------------------------------------------------------------------+
