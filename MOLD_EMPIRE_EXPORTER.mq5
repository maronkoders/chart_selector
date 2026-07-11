#property copyright "Infynite Solutions"
#property version   "1.00"
#property indicator_chart_window
#property indicator_buffers 1
#property indicator_plots   1
#property indicator_label1  "Export"
#property indicator_type1   DRAW_NONE

input string ExportPrefix = "asset_snapshot_";
input bool   ExportOnEveryTick = true;

double dummyBuffer[];
int    hM1_fast,  hM1_slow;
int    hM5_fast,  hM5_slow;
int    hM15_fast, hM15_slow;
int    hM30_fast, hM30_slow;

string SyncLabelName()
  {
   return "MOLD_EXPORT_SYNC_LABEL_" + IntegerToString(ChartID());
  }

void UpdateSyncLabel()
  {
   string name = SyncLabelName();
   if(ObjectFind(0, name) < 0)
     {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_UPPER);
      ObjectSetInteger(0, name, OBJPROP_COLOR, clrDodgerBlue);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 14);
      ObjectSetString(0, name, OBJPROP_FONT, "Arial Bold");
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      ObjectSetInteger(0, name, OBJPROP_BACK, false);
     }

   int width = (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, width / 2);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 0);
   ObjectSetString(0, name, OBJPROP_TEXT, "Syncing data exportation...");
   ChartRedraw(0);
  }

void RemoveSyncLabel()
  {
   ObjectDelete(0, SyncLabelName());
  }

string SafeSymbol(string symbol)
  {
   string s=symbol;
   for(int i=0;i<StringLen(s);i++)
     {
      ushort c=StringGetCharacter(s,i);
      if((c>='A' && c<='Z') || (c>='a' && c<='z') || (c>='0' && c<='9') || c=='_' || c=='-')
         continue;
      StringSetCharacter(s,i, (char)'_');
     }
   return s;
  }

int OnInit()
  {
   SetIndexBuffer(0,dummyBuffer,INDICATOR_DATA);
   PlotIndexSetInteger(0,PLOT_DRAW_TYPE,DRAW_NONE);

   hM1_fast  = iMA(_Symbol, PERIOD_M1, 50, 0, MODE_EMA, PRICE_CLOSE);
   hM1_slow  = iMA(_Symbol, PERIOD_M1,110, 0, MODE_EMA, PRICE_CLOSE);
   hM5_fast  = iMA(_Symbol, PERIOD_M5, 50, 0, MODE_EMA, PRICE_CLOSE);
   hM5_slow  = iMA(_Symbol, PERIOD_M5,110, 0, MODE_EMA, PRICE_CLOSE);
   hM15_fast = iMA(_Symbol, PERIOD_M15,50, 0, MODE_EMA, PRICE_CLOSE);
   hM15_slow = iMA(_Symbol, PERIOD_M15,110,0, MODE_EMA, PRICE_CLOSE);
   hM30_fast = iMA(_Symbol, PERIOD_M30,50, 0, MODE_EMA, PRICE_CLOSE);
   hM30_slow = iMA(_Symbol, PERIOD_M30,110,0, MODE_EMA, PRICE_CLOSE);

   UpdateSyncLabel();
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   RemoveSyncLabel();
   IndicatorRelease(hM1_fast);
   IndicatorRelease(hM1_slow);
   IndicatorRelease(hM5_fast);
   IndicatorRelease(hM5_slow);
   IndicatorRelease(hM15_fast);
   IndicatorRelease(hM15_slow);
   IndicatorRelease(hM30_fast);
   IndicatorRelease(hM30_slow);
  }

void OnChartEvent(const int id,
                  const long &lparam,
                  const double &dparam,
                  const string &sparam)
  {
   if(id == CHARTEVENT_CHART_CHANGE)
      UpdateSyncLabel();
  }

int GetBias(int fastHandle, int slowHandle)
  {
   double fastArr[], slowArr[];
   ArraySetAsSeries(fastArr,true);
   ArraySetAsSeries(slowArr,true);
   if(CopyBuffer(fastHandle,0,1,2,fastArr) < 2) return 0;
   if(CopyBuffer(slowHandle,0,1,2,slowArr) < 2) return 0;
   double delta = fastArr[0] - slowArr[0];
   if(delta > 0) return 1;
   if(delta < 0) return -1;
   return 0;
  }

double GetPrevDayClose()
  {
   double prevClose[];
   if(CopyClose(_Symbol, PERIOD_D1, 1, 1, prevClose) < 1)
      return 0.0;
   return prevClose[0];
  }

double GetDailyChangePercent(double currentPrice)
  {
   double prevClose = GetPrevDayClose();
   if(prevClose <= 0.0) return 0.0;
   return ((currentPrice - prevClose) / prevClose) * 100.0;
  }

void WriteExportFile(double currentPrice, double dailyClose, double dailyChange, int bM1, int bM5, int bM15, int bM30)
  {
   string filename = ExportPrefix + SafeSymbol(_Symbol) + ".json";
   int handle = FileOpen(filename, FILE_WRITE | FILE_ANSI);
   if(handle < 0)
     {
      Print("Failed to open export file: ", filename, " error=", GetLastError());
      return;
     }

   string json = "{\n";
   json += StringFormat("  \"Asset\": \"%s\",\n", _Symbol);
   json += StringFormat("  \"Current Price\": %.6f,\n", currentPrice);
   json += StringFormat("  \"Daily Close\": %s,\n", (dailyClose>0.0) ? DoubleToString(dailyClose,6) : "null");
   json += StringFormat("  \"Daily Change\": %s,\n", (dailyChange!=0.0) ? DoubleToString(dailyChange,6) : "null");
   json += "  \"Bias\": {\n";
   json += StringFormat("    \"M1\": \"%s\",\n", bM1==1?"BUY":bM1==-1?"SELL":"NEUT");
   json += StringFormat("    \"M5\": \"%s\",\n", bM5==1?"BUY":bM5==-1?"SELL":"NEUT");
   json += StringFormat("    \"M15\": \"%s\",\n", bM15==1?"BUY":bM15==-1?"SELL":"NEUT");
   json += StringFormat("    \"M30\": \"%s\"\n", bM30==1?"BUY":bM30==-1?"SELL":"NEUT");
   json += "  }\n";
   json += "}\n";

   FileWriteString(handle, json);
   FileClose(handle);
   Print("Exported snapshot to ", filename);
  }

int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
  {
   if(rates_total < 3)
      return prev_calculated;

   UpdateSyncLabel();

   double currentPrice = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double dailyClose = GetPrevDayClose();
   double dailyChange = GetDailyChangePercent(currentPrice);
   int bM1  = GetBias(hM1_fast,  hM1_slow);
   int bM5  = GetBias(hM5_fast,  hM5_slow);
   int bM15 = GetBias(hM15_fast, hM15_slow);
   int bM30 = GetBias(hM30_fast, hM30_slow);

   if(ExportOnEveryTick)
      WriteExportFile(currentPrice, dailyClose, dailyChange, bM1, bM5, bM15, bM30);

   return rates_total;
  }
