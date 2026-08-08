//+------------------------------------------------------------------+
//|                                        EMA_Ribbon_Bias_M1_M5.mq5 |
//|                        EMA Ribbon (50-110) + M1→M5 Bias          |
//|  Directional bias ONLY when: M1 ribbon crossover, then M5        |
//|  crossover in the SAME direction. M5→M1 order is discarded.      |
//|  Extra M1 crosses do not flip a confirmed bias until a fresh     |
//|  M1→M5 sequence completes in the new direction.                  |
//|                                                                  |
//|  Crossovers are rebuilt from bar history on every new M1 bar, so |
//|  the state never depends on when the indicator was attached.     |
//+------------------------------------------------------------------+
#property copyright   "Infynite Solutions"
#property link        ""
#property version     "2.00"
#property description "EMA Ribbon 50-110 | M1→M5 bias (history replay) + asset_snapshot export"
#property indicator_chart_window
#property indicator_buffers 13
#property indicator_plots   13

//--- Plot 1: EMA 50 (Red)
#property indicator_label1  "EMA 50"
#property indicator_type1   DRAW_LINE
#property indicator_color1  clrRed
#property indicator_style1  STYLE_SOLID
#property indicator_width1  4

//--- Plot 2: EMA 55 (Blue)
#property indicator_label2  "EMA 55"
#property indicator_type2   DRAW_LINE
#property indicator_color2  clrDodgerBlue
#property indicator_style2  STYLE_SOLID
#property indicator_width2  4

//--- Plot 3: EMA 60 (Blue)
#property indicator_label3  "EMA 60"
#property indicator_type3   DRAW_LINE
#property indicator_color3  clrDodgerBlue
#property indicator_style3  STYLE_SOLID
#property indicator_width3  4

//--- Plot 4: EMA 65 (Blue)
#property indicator_label4  "EMA 65"
#property indicator_type4   DRAW_LINE
#property indicator_color4  clrDodgerBlue
#property indicator_style4  STYLE_SOLID
#property indicator_width4  4

//--- Plot 5: EMA 70 (Blue)
#property indicator_label5  "EMA 70"
#property indicator_type5   DRAW_LINE
#property indicator_color5  clrDodgerBlue
#property indicator_style5  STYLE_SOLID
#property indicator_width5  4

//--- Plot 6: EMA 75 (Blue)
#property indicator_label6  "EMA 75"
#property indicator_type6   DRAW_LINE
#property indicator_color6  clrDodgerBlue
#property indicator_style6  STYLE_SOLID
#property indicator_width6  4

//--- Plot 7: EMA 80 (Blue)
#property indicator_label7  "EMA 80"
#property indicator_type7   DRAW_LINE
#property indicator_color7  clrDodgerBlue
#property indicator_style7  STYLE_SOLID
#property indicator_width7  4

//--- Plot 8: EMA 85 (Gold)
#property indicator_label8  "EMA 85"
#property indicator_type8   DRAW_LINE
#property indicator_color8  clrGold
#property indicator_style8  STYLE_SOLID
#property indicator_width8  4

//--- Plot 9: EMA 90 (Gold)
#property indicator_label9  "EMA 90"
#property indicator_type9   DRAW_LINE
#property indicator_color9  clrGold
#property indicator_style9  STYLE_SOLID
#property indicator_width9  4

//--- Plot 10: EMA 95 (Gold)
#property indicator_label10 "EMA 95"
#property indicator_type10  DRAW_LINE
#property indicator_color10 clrGold
#property indicator_style10 STYLE_SOLID
#property indicator_width10 4

//--- Plot 11: EMA 100 (Gold)
#property indicator_label11 "EMA 100"
#property indicator_type11  DRAW_LINE
#property indicator_color11 clrGold
#property indicator_style11 STYLE_SOLID
#property indicator_width11 4

//--- Plot 12: EMA 105 (Gold)
#property indicator_label12 "EMA 105"
#property indicator_type12  DRAW_LINE
#property indicator_color12 clrGold
#property indicator_style12 STYLE_SOLID
#property indicator_width12 4

//--- Plot 13: EMA 110 (Red)
#property indicator_label13 "EMA 110"
#property indicator_type13  DRAW_LINE
#property indicator_color13 clrRed
#property indicator_style13 STYLE_SOLID
#property indicator_width13 4

//--- Inputs
input group "=== Applied Price ==="
input ENUM_APPLIED_PRICE InpAppliedPrice = PRICE_CLOSE; // Applied Price

input group "=== Crossover Detection ==="
input int    InpConfirmBarsM1     = 2;     // M1 closes fully outside ribbon to accept a cross
input int    InpConfirmBarsM5     = 1;     // M5 closes fully outside ribbon to accept a cross
input double InpMinPenetrationPct = 10.0;  // Min penetration past ribbon edge, % of ribbon width
input int    InpPendingExpiryMin  = 30;    // Minutes an M1 lead stays valid (0 = never expires)
input int    InpHistoryBarsM1     = 1440;  // M1 bars replayed to rebuild the sequence

input group "=== Bias / Signals ==="
input bool   InpShowMarkers   = true;   // Draw the current M1→M5 sequence only
input bool   InpShowPending   = true;   // Also mark an M1 lead still waiting for M5
input bool   InpShowDashboard = true;   // Show bias dashboard
input bool   InpEnableAlerts  = true;   // Alert when bias is confirmed
input bool   InpDebug         = false;  // Log crossover / bias decisions

input group "=== Python Dashboard Export ==="
input bool   InpEnableExport     = true;              // Write asset_snapshot_*.json for Streamlit
input string InpExportPrefix     = "asset_snapshot_"; // Same prefix as MOLD_EMPIRE_EXPORTER
input bool   InpExportOnEveryTick = true;             // Keep Files fresh for Filter Assets

input group "=== Marker Colors ==="
input color  InpM1LineColor   = clrSilver;
input color  InpM5LineColor   = clrOrange;
input color  InpBiasBullColor = clrLime;
input color  InpBiasBearColor = clrTomato;

//--- Chart ribbon buffers (PERIOD_CURRENT)
double EMA50_Buffer[];
double EMA55_Buffer[];
double EMA60_Buffer[];
double EMA65_Buffer[];
double EMA70_Buffer[];
double EMA75_Buffer[];
double EMA80_Buffer[];
double EMA85_Buffer[];
double EMA90_Buffer[];
double EMA95_Buffer[];
double EMA100_Buffer[];
double EMA105_Buffer[];
double EMA110_Buffer[];

//--- Chart ribbon handles
int EMA50_Handle,  EMA55_Handle,  EMA60_Handle,  EMA65_Handle;
int EMA70_Handle,  EMA75_Handle,  EMA80_Handle,  EMA85_Handle;
int EMA90_Handle,  EMA95_Handle,  EMA100_Handle, EMA105_Handle, EMA110_Handle;

//--- M1 / M5 ribbon-edge handles (EMA 50 & 110) for crossover detection
int hM1_fast, hM1_slow;
int hM5_fast, hM5_slow;

//--- One detected ribbon crossover
struct XEvent
  {
   datetime          knownTime;   // bar CLOSE time — when the cross became knowable
   datetime          barTime;     // bar OPEN time — used for drawing
   double            price;       // close of the confirming bar
   int               dir;         // +1 bullish, -1 bearish
   int               tfMinutes;   // 1 = M1, 5 = M5
  };

//--- Replayed state (rebuilt from history, never accumulated tick by tick)
int      g_directionalBias  = 0;   // 1 = bullish, -1 = bearish, 0 = none
datetime g_biasConfirmTime  = 0;
int      g_pendingDir       = 0;   // latest M1 lead waiting for M5
datetime g_pendingTime      = 0;
int      g_m1Side           = 0;   // current confirmed ribbon side per TF
int      g_m5Side           = 0;

//--- Only the sequence in force is kept for drawing; older ones are dropped
XEvent   g_leadEvent;              // M1 leg of the confirmed sequence
XEvent   g_confirmEvent;           // M5 leg of the confirmed sequence
bool     g_hasSequence      = false;
XEvent   g_pendingEvent;           // M1 lead still waiting for its M5
bool     g_hasPendingEvent  = false;

datetime g_lastReplayBar    = 0;   // M1 bar the last replay ran on
datetime g_lastAlertedTime  = 0;
bool     g_firstReplayDone  = false;

int      g_lastExportedBias = 999;   // force first write
int      g_lastExportedPend = 999;
int      g_lastExportedM1   = 999;
int      g_lastExportedM5   = 999;

string   DASH_PREFIX        = "ERB_DASH_";
string   MARK_PREFIX        = "ERB_MARK_";

//+------------------------------------------------------------------+
int OnInit()
  {
   SetIndexBuffer(0,  EMA50_Buffer,  INDICATOR_DATA);
   SetIndexBuffer(1,  EMA55_Buffer,  INDICATOR_DATA);
   SetIndexBuffer(2,  EMA60_Buffer,  INDICATOR_DATA);
   SetIndexBuffer(3,  EMA65_Buffer,  INDICATOR_DATA);
   SetIndexBuffer(4,  EMA70_Buffer,  INDICATOR_DATA);
   SetIndexBuffer(5,  EMA75_Buffer,  INDICATOR_DATA);
   SetIndexBuffer(6,  EMA80_Buffer,  INDICATOR_DATA);
   SetIndexBuffer(7,  EMA85_Buffer,  INDICATOR_DATA);
   SetIndexBuffer(8,  EMA90_Buffer,  INDICATOR_DATA);
   SetIndexBuffer(9,  EMA95_Buffer,  INDICATOR_DATA);
   SetIndexBuffer(10, EMA100_Buffer, INDICATOR_DATA);
   SetIndexBuffer(11, EMA105_Buffer, INDICATOR_DATA);
   SetIndexBuffer(12, EMA110_Buffer, INDICATOR_DATA);

   EMA50_Handle  = iMA(_Symbol, PERIOD_CURRENT, 50,  0, MODE_EMA, InpAppliedPrice);
   EMA55_Handle  = iMA(_Symbol, PERIOD_CURRENT, 55,  0, MODE_EMA, InpAppliedPrice);
   EMA60_Handle  = iMA(_Symbol, PERIOD_CURRENT, 60,  0, MODE_EMA, InpAppliedPrice);
   EMA65_Handle  = iMA(_Symbol, PERIOD_CURRENT, 65,  0, MODE_EMA, InpAppliedPrice);
   EMA70_Handle  = iMA(_Symbol, PERIOD_CURRENT, 70,  0, MODE_EMA, InpAppliedPrice);
   EMA75_Handle  = iMA(_Symbol, PERIOD_CURRENT, 75,  0, MODE_EMA, InpAppliedPrice);
   EMA80_Handle  = iMA(_Symbol, PERIOD_CURRENT, 80,  0, MODE_EMA, InpAppliedPrice);
   EMA85_Handle  = iMA(_Symbol, PERIOD_CURRENT, 85,  0, MODE_EMA, InpAppliedPrice);
   EMA90_Handle  = iMA(_Symbol, PERIOD_CURRENT, 90,  0, MODE_EMA, InpAppliedPrice);
   EMA95_Handle  = iMA(_Symbol, PERIOD_CURRENT, 95,  0, MODE_EMA, InpAppliedPrice);
   EMA100_Handle = iMA(_Symbol, PERIOD_CURRENT, 100, 0, MODE_EMA, InpAppliedPrice);
   EMA105_Handle = iMA(_Symbol, PERIOD_CURRENT, 105, 0, MODE_EMA, InpAppliedPrice);
   EMA110_Handle = iMA(_Symbol, PERIOD_CURRENT, 110, 0, MODE_EMA, InpAppliedPrice);

   hM1_fast = iMA(_Symbol, PERIOD_M1, 50,  0, MODE_EMA, InpAppliedPrice);
   hM1_slow = iMA(_Symbol, PERIOD_M1, 110, 0, MODE_EMA, InpAppliedPrice);
   hM5_fast = iMA(_Symbol, PERIOD_M5, 50,  0, MODE_EMA, InpAppliedPrice);
   hM5_slow = iMA(_Symbol, PERIOD_M5, 110, 0, MODE_EMA, InpAppliedPrice);

   if(EMA50_Handle  == INVALID_HANDLE || EMA55_Handle  == INVALID_HANDLE ||
      EMA60_Handle  == INVALID_HANDLE || EMA65_Handle  == INVALID_HANDLE ||
      EMA70_Handle  == INVALID_HANDLE || EMA75_Handle  == INVALID_HANDLE ||
      EMA80_Handle  == INVALID_HANDLE || EMA85_Handle  == INVALID_HANDLE ||
      EMA90_Handle  == INVALID_HANDLE || EMA95_Handle  == INVALID_HANDLE ||
      EMA100_Handle == INVALID_HANDLE || EMA105_Handle == INVALID_HANDLE ||
      EMA110_Handle == INVALID_HANDLE ||
      hM1_fast == INVALID_HANDLE || hM1_slow == INVALID_HANDLE ||
      hM5_fast == INVALID_HANDLE || hM5_slow == INVALID_HANDLE)
     {
      Print("Error creating EMA handles. Error code: ", GetLastError());
      return(INIT_FAILED);
     }

   IndicatorSetString(INDICATOR_SHORTNAME, "EMA Ribbon Bias (M1→M5)");
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   IndicatorRelease(EMA50_Handle);  IndicatorRelease(EMA55_Handle);
   IndicatorRelease(EMA60_Handle);  IndicatorRelease(EMA65_Handle);
   IndicatorRelease(EMA70_Handle);  IndicatorRelease(EMA75_Handle);
   IndicatorRelease(EMA80_Handle);  IndicatorRelease(EMA85_Handle);
   IndicatorRelease(EMA90_Handle);  IndicatorRelease(EMA95_Handle);
   IndicatorRelease(EMA100_Handle); IndicatorRelease(EMA105_Handle);
   IndicatorRelease(EMA110_Handle);
   IndicatorRelease(hM1_fast); IndicatorRelease(hM1_slow);
   IndicatorRelease(hM5_fast); IndicatorRelease(hM5_slow);

   ObjectsDeleteAll(0, DASH_PREFIX);
   ObjectsDeleteAll(0, MARK_PREFIX);
   Comment("");
  }

//+------------------------------------------------------------------+
//| Formatting helpers                                                |
//+------------------------------------------------------------------+
string DirStr(const int dir)
  {
   if(dir > 0) return "BULLISH";
   if(dir < 0) return "BEARISH";
   return "NONE";
  }

string BiasJson(const int dir)
  {
   if(dir > 0) return "BUY";
   if(dir < 0) return "SELL";
   return "NEUT";
  }

color DirColor(const int dir)
  {
   if(dir > 0) return InpBiasBullColor;
   if(dir < 0) return InpBiasBearColor;
   return clrSilver;
  }

string SafeSymbol(string symbol)
  {
   string s = symbol;
   for(int i = 0; i < StringLen(s); i++)
     {
      ushort c = StringGetCharacter(s, i);
      if((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
         (c >= '0' && c <= '9') || c == '_' || c == '-')
         continue;
      StringSetCharacter(s, i, (ushort)'_');
     }
   return s;
  }

//+------------------------------------------------------------------+
//| Price fully above (+1) / fully below (-1) the ribbon, else 0.    |
//| A close must clear the nearest edge by InpMinPenetrationPct of   |
//| the ribbon width, so grazing the edge is not a crossover.        |
//+------------------------------------------------------------------+
int RibbonSide(const double closePrice, const double emaFast, const double emaSlow)
  {
   double upper  = MathMax(emaFast, emaSlow);
   double lower  = MathMin(emaFast, emaSlow);
   double buffer = (upper - lower) * (InpMinPenetrationPct / 100.0);

   if(closePrice > upper + buffer) return  1;
   if(closePrice < lower - buffer) return -1;
   return 0;
  }

//+------------------------------------------------------------------+
//| Rebuild every ribbon crossover on one timeframe from bar history.|
//| A side change counts only after InpConfirmBars closes hold the   |
//| new side, which removes single-bar whipsaw crossings.            |
//+------------------------------------------------------------------+
bool ScanTFEvents(const ENUM_TIMEFRAMES tf,
                  const int hFast,
                  const int hSlow,
                  const int wantBars,
                  const int confirmBars,
                  XEvent &events[],
                  int &finalSide)
  {
   ArrayFree(events);
   finalSide = 0;

   int available = Bars(_Symbol, tf);
   if(available < 150) return false;

   int bars = MathMin(wantBars, available - 2);
   if(bars < 20) return false;

   double closes[], fast[], slow[];
   datetime times[];
   ArraySetAsSeries(closes, false);
   ArraySetAsSeries(fast,   false);
   ArraySetAsSeries(slow,   false);
   ArraySetAsSeries(times,  false);

   // start_pos 1 skips the live bar; data arrives oldest → newest
   int gotC = CopyClose (_Symbol, tf, 1, bars, closes);
   int gotT = CopyTime  (_Symbol, tf, 1, bars, times);
   int gotF = CopyBuffer(hFast, 0, 1, bars, fast);
   int gotS = CopyBuffer(hSlow, 0, 1, bars, slow);
   if(gotC <= 0 || gotT <= 0 || gotF <= 0 || gotS <= 0) return false;

   // Re-copy everything at the shortest length so all four arrays stay aligned
   int usable = MathMin(MathMin(gotC, gotT), MathMin(gotF, gotS));
   if(usable < 20) return false;
   if(usable < bars)
     {
      bars = usable;
      if(CopyClose (_Symbol, tf, 1, bars, closes) < bars) return false;
      if(CopyTime  (_Symbol, tf, 1, bars, times)  < bars) return false;
      if(CopyBuffer(hFast, 0, 1, bars, fast)      < bars) return false;
      if(CopyBuffer(hSlow, 0, 1, bars, slow)      < bars) return false;
     }

   int period  = PeriodSeconds(tf);
   int need    = MathMax(1, confirmBars);
   int settled = 0;   // side currently held
   int cand    = 0;   // side trying to take over
   int candRun = 0;

   for(int i = 0; i < bars; i++)
     {
      if(fast[i] == EMPTY_VALUE || slow[i] == EMPTY_VALUE) continue;
      if(fast[i] <= 0.0 || slow[i] <= 0.0)                 continue;

      int side = RibbonSide(closes[i], fast[i], slow[i]);

      // Inside the ribbon, or still on the held side → no pending flip
      if(side == 0 || side == settled)
        {
         cand    = 0;
         candRun = 0;
         continue;
        }

      if(side == cand)
         candRun++;
      else
        {
         cand    = side;
         candRun = 1;
        }

      if(candRun < need)
         continue;

      // The very first settled side is the starting state, not a crossover
      if(settled != 0)
        {
         int n = ArraySize(events);
         ArrayResize(events, n + 1);
         events[n].knownTime = times[i] + period;
         events[n].barTime   = times[i];
         events[n].price     = closes[i];
         events[n].dir       = side;
         events[n].tfMinutes = period / 60;
        }

      settled = side;
      cand    = 0;
      candRun = 0;
     }

   finalSide = settled;
   return true;
  }

//+------------------------------------------------------------------+
//| Merge M1 and M5 events by the time each became knowable (bar     |
//| close). On equal times M1 sorts first, since an M1 cross inside  |
//| an M5 bar always precedes that M5 bar's close.                   |
//+------------------------------------------------------------------+
void MergeEvents(const XEvent &m1[], const XEvent &m5[], XEvent &merged[])
  {
   int n1 = ArraySize(m1);
   int n5 = ArraySize(m5);
   ArrayResize(merged, n1 + n5);

   int i = 0, j = 0, k = 0;
   while(i < n1 && j < n5)
     {
      bool takeM1;
      if(m1[i].knownTime != m5[j].knownTime)
         takeM1 = (m1[i].knownTime < m5[j].knownTime);
      else
         takeM1 = true;

      if(takeM1) { merged[k] = m1[i]; i++; }
      else       { merged[k] = m5[j]; j++; }
      k++;
     }
   while(i < n1) { merged[k] = m1[i]; i++; k++; }
   while(j < n5) { merged[k] = m5[j]; j++; k++; }
  }

//+------------------------------------------------------------------+
//| Replay the sequence rules over the merged crossover list.        |
//|  - An M1 cross arms (or re-arms) the lead in its direction.      |
//|  - An M5 cross confirms bias only if it matches the armed lead   |
//|    and became knowable at or after it.                           |
//|  - An M5 cross with no lead (M5→M1 order) or against the lead    |
//|    breaks the sequence; bias is left untouched.                  |
//+------------------------------------------------------------------+
void ReplaySequence(const XEvent &events[])
  {
   int      bias        = 0;
   datetime biasTime    = 0;
   int      pending     = 0;
   datetime pendingTime = 0;
   long     expiry      = (long)InpPendingExpiryMin * 60;

   XEvent leadEvt, confirmEvt, pendingEvt;
   ZeroMemory(leadEvt);
   ZeroMemory(confirmEvt);
   ZeroMemory(pendingEvt);
   bool hasSequence = false;

   int total = ArraySize(events);
   for(int i = 0; i < total; i++)
     {
      // A lead that waited too long for its M5 is no longer valid
      if(pending != 0 && expiry > 0 &&
         (long)(events[i].knownTime - pendingTime) > expiry)
        {
         pending     = 0;
         pendingTime = 0;
        }

      if(events[i].tfMinutes == 1)
        {
         // Latest M1 cross is the lead the next M5 must confirm
         pending     = events[i].dir;
         pendingTime = events[i].knownTime;
         pendingEvt  = events[i];
         continue;
        }

      if(pending == 0)
         continue;   // M5 arrived first — discard, keep existing bias

      if(events[i].dir != pending || events[i].knownTime < pendingTime)
        {
         pending     = 0;   // sequence broken
         pendingTime = 0;
         continue;
        }

      // Newest valid pair replaces the previous one, so only the sequence
      // currently in force is ever kept or drawn.
      bias        = events[i].dir;
      biasTime    = events[i].knownTime;
      leadEvt     = pendingEvt;
      confirmEvt  = events[i];
      hasSequence = true;
      pending     = 0;
      pendingTime = 0;
     }

   // Expire a lead that is still waiting as of now
   if(pending != 0 && expiry > 0 &&
      (long)(TimeCurrent() - pendingTime) > expiry)
     {
      pending     = 0;
      pendingTime = 0;
     }

   g_directionalBias  = bias;
   g_biasConfirmTime  = biasTime;
   g_pendingDir       = pending;
   g_pendingTime      = pendingTime;
   g_leadEvent        = leadEvt;
   g_confirmEvent     = confirmEvt;
   g_hasSequence      = hasSequence;
   g_pendingEvent     = pendingEvt;
   g_hasPendingEvent  = (pending != 0);
  }

//+------------------------------------------------------------------+
void DrawCrossoverMarker(const XEvent &e, const string id, const string label,
                         const ENUM_LINE_STYLE style)
  {
   color  clr   = (e.tfMinutes == 1) ? InpM1LineColor : InpM5LineColor;
   string vname = MARK_PREFIX + id + "_V";
   string tname = MARK_PREFIX + id + "_T";

   if(ObjectFind(0, vname) < 0)
      ObjectCreate(0, vname, OBJ_VLINE, 0, e.barTime, 0);
   ObjectSetInteger(0, vname, OBJPROP_TIME,       e.barTime);
   ObjectSetInteger(0, vname, OBJPROP_COLOR,      clr);
   ObjectSetInteger(0, vname, OBJPROP_STYLE,      style);
   ObjectSetInteger(0, vname, OBJPROP_WIDTH,      1);
   ObjectSetInteger(0, vname, OBJPROP_BACK,       true);
   ObjectSetInteger(0, vname, OBJPROP_SELECTABLE, false);

   if(ObjectFind(0, tname) < 0)
      ObjectCreate(0, tname, OBJ_TEXT, 0, e.barTime, e.price);
   ObjectMove(0, tname, 0, e.barTime, e.price);
   ObjectSetString (0, tname, OBJPROP_TEXT,
                    StringFormat("%s (%s)", label, DirStr(e.dir)));
   ObjectSetInteger(0, tname, OBJPROP_COLOR,      DirColor(e.dir));
   ObjectSetInteger(0, tname, OBJPROP_FONTSIZE,   8);
   ObjectSetString (0, tname, OBJPROP_FONT,       "Consolas");
   ObjectSetInteger(0, tname, OBJPROP_ANCHOR,     ANCHOR_LEFT_LOWER);
   ObjectSetInteger(0, tname, OBJPROP_SELECTABLE, false);
  }

//+------------------------------------------------------------------+
//| Draw only the sequence in force: the M1 lead and the M5 that     |
//| confirmed it, plus an M1 lead still waiting. Superseded pairs    |
//| are wiped, so the chart never shows stale sequences.             |
//+------------------------------------------------------------------+
void DrawSequenceMarkers()
  {
   ObjectsDeleteAll(0, MARK_PREFIX);
   if(!InpShowMarkers) return;

   if(g_hasSequence)
     {
      DrawCrossoverMarker(g_leadEvent,    "SEQ_M1", "M1 Crossover", STYLE_SOLID);
      DrawCrossoverMarker(g_confirmEvent, "SEQ_M5", "M5 Crossover", STYLE_SOLID);
     }

   if(InpShowPending && g_hasPendingEvent)
      DrawCrossoverMarker(g_pendingEvent, "LEAD_M1", "M1 lead - waiting M5", STYLE_DOT);
  }

//+------------------------------------------------------------------+
void DashLabel(const string id, const string text, const int x, const int y, const color clr)
  {
   string name = DASH_PREFIX + id;
   if(ObjectFind(0, name) < 0)
     {
      ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetString (0, name, OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 10);
     }
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_RIGHT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR, ANCHOR_RIGHT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetString (0, name, OBJPROP_TEXT, text);
  }

void UpdateDashboard()
  {
   if(!InpShowDashboard) return;

   // Distances are from the top-right chart corner
   int x = 12, y = 24, dy = 16;

   string confirmed = (g_biasConfirmTime > 0)
                      ? TimeToString(g_biasConfirmTime, TIME_MINUTES)
                      : "--:--";

   DashLabel("title", "EMA Ribbon Bias (M1→M5 only)", x, y, clrAqua);
   DashLabel("bias",  StringFormat("Directional Bias : %s", DirStr(g_directionalBias)),
             x, y + dy, DirColor(g_directionalBias));
   DashLabel("since", StringFormat("Confirmed at     : %s", confirmed),
             x, y + 2 * dy, clrSilver);
   DashLabel("pend",  StringFormat("Pending M1 lead  : %s", DirStr(g_pendingDir)),
             x, y + 3 * dy, (g_pendingDir == 0 ? clrSilver : clrGold));
   DashLabel("sides", StringFormat("Ribbon M1 / M5   : %s / %s",
                                   BiasJson(g_m1Side), BiasJson(g_m5Side)),
             x, y + 4 * dy, clrSilver);
   DashLabel("rule",  InpEnableExport ? "Export: ON → MQL5/Files/asset_snapshot_*.json"
                                      : "Export: OFF",
             x, y + 5 * dy, InpEnableExport ? clrDodgerBlue : clrDimGray);
  }

//+------------------------------------------------------------------+
double GetPrevDayClose()
  {
   double prevClose[];
   if(CopyClose(_Symbol, PERIOD_D1, 1, 1, prevClose) < 1)
      return 0.0;
   return prevClose[0];
  }

double GetDailyChangePercent(const double currentPrice)
  {
   double prevClose = GetPrevDayClose();
   if(prevClose <= 0.0) return 0.0;
   return ((currentPrice - prevClose) / prevClose) * 100.0;
  }

//+------------------------------------------------------------------+
//| Write MQL5/Files/asset_snapshot_<symbol>.json for the dashboard  |
//| Bias.M1 / Bias.M5 = current ribbon side on each TF               |
//| SequentialBias    = confirmed M1→M5 directional bias             |
//+------------------------------------------------------------------+
void WriteExportFile()
  {
   if(!InpEnableExport)
      return;

   double currentPrice = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(currentPrice <= 0.0)
      currentPrice = SymbolInfoDouble(_Symbol, SYMBOL_LAST);
   double dailyClose  = GetPrevDayClose();
   double dailyChange = GetDailyChangePercent(currentPrice);

   // Skip redundant writes unless tick-export is on (keeps mtime fresh).
   if(!InpExportOnEveryTick &&
      g_m1Side == g_lastExportedM1 &&
      g_m5Side == g_lastExportedM5 &&
      g_directionalBias == g_lastExportedBias &&
      g_pendingDir == g_lastExportedPend)
      return;

   string filename = InpExportPrefix + SafeSymbol(_Symbol) + ".json";
   int handle = FileOpen(filename, FILE_WRITE | FILE_ANSI | FILE_TXT);
   if(handle == INVALID_HANDLE)
     {
      Print("Failed to open export file: ", filename, " error=", GetLastError());
      return;
     }

   string json = "{\n";
   json += StringFormat("  \"Asset\": \"%s\",\n", _Symbol);
   json += StringFormat("  \"Current Price\": %.6f,\n", currentPrice);
   json += StringFormat("  \"Daily Close\": %s,\n",
                        (dailyClose > 0.0) ? DoubleToString(dailyClose, 6) : "null");
   json += StringFormat("  \"Daily Change\": %s,\n",
                        DoubleToString(dailyChange, 6));
   json += "  \"Bias\": {\n";
   json += StringFormat("    \"M1\": \"%s\",\n", BiasJson(g_m1Side));
   json += StringFormat("    \"M5\": \"%s\",\n", BiasJson(g_m5Side));
   json += "    \"M15\": \"NEUT\",\n";
   json += "    \"M30\": \"NEUT\"\n";
   json += "  },\n";
   json += StringFormat("  \"SequentialBias\": \"%s\",\n", BiasJson(g_directionalBias));
   json += StringFormat("  \"PendingM1\": \"%s\",\n", BiasJson(g_pendingDir));
   json += StringFormat("  \"ConfirmedAt\": \"%s\",\n",
                        (g_biasConfirmTime > 0) ? TimeToString(g_biasConfirmTime) : "");
   json += "  \"Source\": \"EMA_Ribbon_Bias_M1_M5\"\n";
   json += "}\n";

   FileWriteString(handle, json);
   FileClose(handle);

   g_lastExportedM1   = g_m1Side;
   g_lastExportedM5   = g_m5Side;
   g_lastExportedBias = g_directionalBias;
   g_lastExportedPend = g_pendingDir;

   if(InpDebug)
      Print("Exported snapshot to ", filename,
            " | M1=", BiasJson(g_m1Side),
            " M5=", BiasJson(g_m5Side),
            " Sequential=", BiasJson(g_directionalBias));
  }

//+------------------------------------------------------------------+
//| Rebuild bias from history. Runs once per closed M1 bar.          |
//+------------------------------------------------------------------+
void RebuildBias()
  {
   XEvent m1Events[], m5Events[], merged[];
   int m1Side = 0, m5Side = 0;

   int barsM1 = MathMax(300, InpHistoryBarsM1);
   int barsM5 = barsM1 / 5 + 150;

   if(!ScanTFEvents(PERIOD_M1, hM1_fast, hM1_slow, barsM1, InpConfirmBarsM1, m1Events, m1Side))
      return;
   if(!ScanTFEvents(PERIOD_M5, hM5_fast, hM5_slow, barsM5, InpConfirmBarsM5, m5Events, m5Side))
      return;

   g_m1Side = m1Side;
   g_m5Side = m5Side;

   MergeEvents(m1Events, m5Events, merged);
   ReplaySequence(merged);
   DrawSequenceMarkers();

   if(InpDebug)
      Print(StringFormat("Replay: %d M1 + %d M5 crossovers | bias=%s pending=%s",
            ArraySize(m1Events), ArraySize(m5Events),
            DirStr(g_directionalBias), DirStr(g_pendingDir)));

   // Alert only for a confirmation that is both new and recent, so reloading
   // the indicator never re-fires historical signals.
   bool isNew    = (g_directionalBias != 0 && g_biasConfirmTime != g_lastAlertedTime);
   bool isRecent = (TimeCurrent() - g_biasConfirmTime) <= 2 * PeriodSeconds(PERIOD_M5);

   if(isNew)
     {
      g_lastAlertedTime = g_biasConfirmTime;
      string msg = StringFormat("%s directional bias CONFIRMED (M1→M5) — %s",
                                DirStr(g_directionalBias), _Symbol);
      Comment(msg);
      if(InpEnableAlerts && g_firstReplayDone && isRecent)
         Alert(msg);
     }

   g_firstReplayDone = true;
  }

//+------------------------------------------------------------------+
bool CopyRibbon(const int handle, double &buf[], const int rates_total, const int prev_calculated)
  {
   int count = (prev_calculated == 0) ? rates_total : (rates_total - prev_calculated + 1);
   if(count < 1) count = 1;
   if(count > rates_total) count = rates_total;
   return(CopyBuffer(handle, 0, 0, count, buf) >= count);
  }

//+------------------------------------------------------------------+
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
   if(rates_total < 120)
      return(0);

   if(!CopyRibbon(EMA50_Handle,  EMA50_Buffer,  rates_total, prev_calculated)) return(0);
   if(!CopyRibbon(EMA55_Handle,  EMA55_Buffer,  rates_total, prev_calculated)) return(0);
   if(!CopyRibbon(EMA60_Handle,  EMA60_Buffer,  rates_total, prev_calculated)) return(0);
   if(!CopyRibbon(EMA65_Handle,  EMA65_Buffer,  rates_total, prev_calculated)) return(0);
   if(!CopyRibbon(EMA70_Handle,  EMA70_Buffer,  rates_total, prev_calculated)) return(0);
   if(!CopyRibbon(EMA75_Handle,  EMA75_Buffer,  rates_total, prev_calculated)) return(0);
   if(!CopyRibbon(EMA80_Handle,  EMA80_Buffer,  rates_total, prev_calculated)) return(0);
   if(!CopyRibbon(EMA85_Handle,  EMA85_Buffer,  rates_total, prev_calculated)) return(0);
   if(!CopyRibbon(EMA90_Handle,  EMA90_Buffer,  rates_total, prev_calculated)) return(0);
   if(!CopyRibbon(EMA95_Handle,  EMA95_Buffer,  rates_total, prev_calculated)) return(0);
   if(!CopyRibbon(EMA100_Handle, EMA100_Buffer, rates_total, prev_calculated)) return(0);
   if(!CopyRibbon(EMA105_Handle, EMA105_Buffer, rates_total, prev_calculated)) return(0);
   if(!CopyRibbon(EMA110_Handle, EMA110_Buffer, rates_total, prev_calculated)) return(0);

   // Full replay once per closed M1 bar — cheap and immune to missed ticks.
   datetime m1Bar = iTime(_Symbol, PERIOD_M1, 1);
   if(m1Bar > 0 && m1Bar != g_lastReplayBar)
     {
      g_lastReplayBar = m1Bar;
      RebuildBias();
     }

   UpdateDashboard();
   WriteExportFile();

   return(rates_total);
  }
//+------------------------------------------------------------------+
