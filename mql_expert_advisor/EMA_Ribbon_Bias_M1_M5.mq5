//+------------------------------------------------------------------+
//|                                        EMA_Ribbon_Bias_M1_M5.mq5 |
//|                        EMA Ribbon (50-110) + M1→M5 Bias          |
//|  Directional bias ONLY when: M1 ribbon crossover, then M5        |
//|  crossover in the SAME direction. M5→M1 order is discarded.      |
//|  Extra M1 crosses while waiting / after bias do not flip bias    |
//|  until a fresh M1→M5 sequence confirms the new direction.        |
//+------------------------------------------------------------------+
#property copyright   "Infynite Solutions"
#property link        ""
#property version     "1.00"
#property description "EMA Ribbon 50-110 | Bias = M1 crossover followed by M5 crossover"
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

input group "=== Bias / Signals ==="
input bool   InpShowMarkers   = true;   // Draw M1/M5 crossover markers
input bool   InpShowDashboard = true;   // Show bias dashboard
input bool   InpEnableAlerts  = true;   // Alert when bias is confirmed
input bool   InpDebug         = false;  // Log crossover / bias decisions

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

//--- Sequence state
// pendingDir: armed by first M1 crossover while idle (1=bull, -1=bear, 0=none)
// directionalBias: confirmed only after matching M5 crossover that FOLLOWED that M1
int      g_pendingDir       = 0;
datetime g_pendingM1Time    = 0;
double   g_pendingM1Price   = 0;
int      g_directionalBias  = 0;   // 1=bullish, -1=bearish, 0=none
datetime g_biasConfirmTime  = 0;
double   g_biasConfirmPrice = 0;

// Last clear side of price vs ribbon: 1=fully above, -1=fully below, 0=unset
int      g_m1LastSide       = 0;
int      g_m5LastSide       = 0;

datetime g_lastM1BarTime    = 0;
datetime g_lastM5BarTime    = 0;
int      g_markerSerial     = 0;

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
  }

//+------------------------------------------------------------------+
//| Price fully above (+1) / fully below (-1) ribbon edges, else 0   |
//+------------------------------------------------------------------+
int RibbonSide(const double closePrice, const double emaFast, const double emaSlow)
  {
   if(closePrice > emaFast && closePrice > emaSlow) return  1;
   if(closePrice < emaFast && closePrice < emaSlow) return -1;
   return 0;
  }

string DirStr(const int dir)
  {
   if(dir > 0) return "BULLISH";
   if(dir < 0) return "BEARISH";
   return "NONE";
  }

color DirColor(const int dir)
  {
   if(dir > 0) return InpBiasBullColor;
   if(dir < 0) return InpBiasBearColor;
   return clrSilver;
  }

//+------------------------------------------------------------------+
//| Detect ribbon pierce using last clear side on closed bars.       |
//| Returns +1 bullish cross (below→above), -1 bearish (above→below) |
//+------------------------------------------------------------------+
int DetectRibbonCrossover(const ENUM_TIMEFRAMES tf,
                          const int hFast, const int hSlow,
                          int &lastClearSide,
                          datetime &outBarTime,
                          double &outClose)
  {
   outBarTime = 0;
   outClose   = 0;

   // Closed bar only (shift 1)
   double closeArr[], fastArr[], slowArr[];
   ArraySetAsSeries(closeArr, true);
   ArraySetAsSeries(fastArr, true);
   ArraySetAsSeries(slowArr, true);

   if(CopyClose(_Symbol, tf, 1, 1, closeArr) < 1) return 0;
   if(CopyBuffer(hFast, 0, 1, 1, fastArr) < 1)     return 0;
   if(CopyBuffer(hSlow, 0, 1, 1, slowArr) < 1)      return 0;

   datetime barTime = iTime(_Symbol, tf, 1);
   if(barTime <= 0) return 0;

   int side = RibbonSide(closeArr[0], fastArr[0], slowArr[0]);
   outBarTime = barTime;
   outClose   = closeArr[0];

   if(side == 0)
      return 0;   // still inside ribbon — wait for a clear side

   if(lastClearSide == 0)
     {
      lastClearSide = side;
      return 0;
     }

   if(side == lastClearSide)
      return 0;

   // Clear side flipped → full ribbon crossover in the new side's direction
   int cross = side;
   lastClearSide = side;
   return cross;
  }

//+------------------------------------------------------------------+
void DrawCrossoverMarker(const string tag,
                         const datetime t,
                         const double price,
                         const color clr,
                         const string label)
  {
   if(!InpShowMarkers || t <= 0) return;

   g_markerSerial++;
   string vname = StringFormat("%s%s_%d_V", MARK_PREFIX, tag, g_markerSerial);
   string tname = StringFormat("%s%s_%d_T", MARK_PREFIX, tag, g_markerSerial);
   string hname = StringFormat("%s%s_%d_H", MARK_PREFIX, tag, g_markerSerial);

   if(ObjectFind(0, vname) < 0)
     {
      ObjectCreate(0, vname, OBJ_VLINE, 0, t, 0);
      ObjectSetInteger(0, vname, OBJPROP_COLOR, clr);
      ObjectSetInteger(0, vname, OBJPROP_STYLE, STYLE_SOLID);
      ObjectSetInteger(0, vname, OBJPROP_WIDTH, 1);
      ObjectSetInteger(0, vname, OBJPROP_BACK, true);
      ObjectSetInteger(0, vname, OBJPROP_SELECTABLE, false);
     }
   else
      ObjectSetInteger(0, vname, OBJPROP_TIME, t);

   if(ObjectFind(0, tname) < 0)
     {
      ObjectCreate(0, tname, OBJ_TEXT, 0, t, price);
      ObjectSetInteger(0, tname, OBJPROP_COLOR, clrWhite);
      ObjectSetInteger(0, tname, OBJPROP_FONTSIZE, 8);
      ObjectSetString (0, tname, OBJPROP_FONT, "Consolas");
      ObjectSetInteger(0, tname, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);
      ObjectSetInteger(0, tname, OBJPROP_SELECTABLE, false);
     }
   ObjectSetString(0, tname, OBJPROP_TEXT, label);
   ObjectMove(0, tname, 0, t, price);

   // Horizontal ray from crossover price (matches annotated chart)
   datetime t2 = t + PeriodSeconds(PERIOD_M5) * 12;
   if(ObjectFind(0, hname) < 0)
     {
      ObjectCreate(0, hname, OBJ_TREND, 0, t, price, t2, price);
      ObjectSetInteger(0, hname, OBJPROP_COLOR, clrWhite);
      ObjectSetInteger(0, hname, OBJPROP_WIDTH, 1);
      ObjectSetInteger(0, hname, OBJPROP_RAY_RIGHT, false);
      ObjectSetInteger(0, hname, OBJPROP_SELECTABLE, false);
     }
   else
     {
      ObjectMove(0, hname, 0, t, price);
      ObjectMove(0, hname, 1, t2, price);
     }
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
   DashLabel("title", "EMA Ribbon Bias (M1→M5 only)", x, y, clrAqua);
   DashLabel("bias",  StringFormat("Directional Bias : %s", DirStr(g_directionalBias)),
             x, y + dy, DirColor(g_directionalBias));
   DashLabel("pend",  StringFormat("Pending M1       : %s", DirStr(g_pendingDir)),
             x, y + 2 * dy, (g_pendingDir == 0 ? clrSilver : clrGold));
   DashLabel("rule",  "Rule: M1 cross then M5 cross (same dir)",
             x, y + 3 * dy, clrDimGray);
  }

//+------------------------------------------------------------------+
//| M1 crossover arms pending. Extra M1s do not retarget pending.    |
//| Confirmed bias is never changed by M1 alone.                     |
//+------------------------------------------------------------------+
void HandleM1Crossover(const int cross, const datetime t, const double price)
  {
   if(cross == 0) return;

   DrawCrossoverMarker("M1", t, price, InpM1LineColor,
                       StringFormat("M1 Crossover (%s)", DirStr(cross)));

   if(InpDebug)
      Print(StringFormat("M1 crossover %s @ %s | pending=%s bias=%s",
            DirStr(cross), TimeToString(t), DirStr(g_pendingDir), DirStr(g_directionalBias)));

   // Already waiting for M5 — ignore intermediate M1 crosses (do not retarget)
   if(g_pendingDir != 0)
     {
      if(InpDebug)
         Print("M1 ignored (pending already armed; waiting for M5)");
      return;
     }

   // Arm a new M1→M5 sequence. Existing confirmed bias stays until M5 confirms a flip.
   g_pendingDir     = cross;
   g_pendingM1Time  = t;
   g_pendingM1Price = price;

   if(InpDebug)
      Print(StringFormat("Pending armed: %s (bias still %s until M5 confirms)",
            DirStr(g_pendingDir), DirStr(g_directionalBias)));
  }

//+------------------------------------------------------------------+
//| M5 crossover confirms bias ONLY if a same-direction M1 is armed  |
//| and that M1 occurred earlier. M5-first / wrong-dir is discarded. |
//+------------------------------------------------------------------+
void HandleM5Crossover(const int cross, const datetime t, const double price)
  {
   if(cross == 0) return;

   DrawCrossoverMarker("M5", t, price, InpM5LineColor,
                       StringFormat("M5 Crossover (%s)", DirStr(cross)));

   if(InpDebug)
      Print(StringFormat("M5 crossover %s @ %s | pending=%s bias=%s",
            DirStr(cross), TimeToString(t), DirStr(g_pendingDir), DirStr(g_directionalBias)));

   // No prior M1 → invalid order (M5 first). Discard — do not set/change bias.
   if(g_pendingDir == 0)
     {
      if(InpDebug)
         Print("M5 discarded: no prior M1 (M5→M1 order is invalid)");
      return;
     }

   // M5 must be AFTER the armed M1
   if(t <= g_pendingM1Time)
     {
      if(InpDebug)
         Print("M5 discarded: timestamp not after pending M1");
      return;
     }

   // Direction must match the armed M1
   if(cross != g_pendingDir)
     {
      if(InpDebug)
         Print(StringFormat("M5 discarded: direction %s != pending M1 %s (pending cleared)",
               DirStr(cross), DirStr(g_pendingDir)));
      // Stale / conflicting arm — clear so a fresh M1 can restart the sequence
      g_pendingDir     = 0;
      g_pendingM1Time  = 0;
      g_pendingM1Price = 0;
      return;
     }

   // Valid M1 → M5 sequence: set (or flip) directional bias
   g_directionalBias  = cross;
   g_biasConfirmTime  = t;
   g_biasConfirmPrice = price;

   if(InpDebug)
      Print(StringFormat("BIAS CONFIRMED %s (M1 @ %s → M5 @ %s)",
            DirStr(g_directionalBias),
            TimeToString(g_pendingM1Time),
            TimeToString(t)));

   // Clear pending; further M1s alone will not change bias until a new M1→M5 completes
   g_pendingDir     = 0;
   g_pendingM1Time  = 0;
   g_pendingM1Price = 0;

   if(InpEnableAlerts)
     {
      string msg = StringFormat("%s directional bias CONFIRMED (M1→M5) — %s",
                                DirStr(g_directionalBias), _Symbol);
      Alert(msg);
      Comment(msg);
     }
  }

//+------------------------------------------------------------------+
void ProcessBiasLogic()
  {
   // Process new closed M1 bar
   datetime m1Bar = iTime(_Symbol, PERIOD_M1, 1);
   if(m1Bar > 0 && m1Bar != g_lastM1BarTime)
     {
      g_lastM1BarTime = m1Bar;
      datetime xt = 0;
      double xp = 0;
      int cross = DetectRibbonCrossover(PERIOD_M1, hM1_fast, hM1_slow, g_m1LastSide, xt, xp);
      if(cross != 0)
         HandleM1Crossover(cross, xt, xp);
     }

   // Process new closed M5 bar
   datetime m5Bar = iTime(_Symbol, PERIOD_M5, 1);
   if(m5Bar > 0 && m5Bar != g_lastM5BarTime)
     {
      g_lastM5BarTime = m5Bar;
      datetime xt = 0;
      double xp = 0;
      int cross = DetectRibbonCrossover(PERIOD_M5, hM5_fast, hM5_slow, g_m5LastSide, xt, xp);
      if(cross != 0)
         HandleM5Crossover(cross, xt, xp);
     }

   UpdateDashboard();
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

   ProcessBiasLogic();
   return(rates_total);
  }
//+------------------------------------------------------------------+
