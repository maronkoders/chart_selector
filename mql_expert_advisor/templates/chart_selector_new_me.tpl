<chart>
symbol=
period_type=0
period_size=1
digits=3
tick_size=0.001000
position_time=0
scale_fix=0
scale_fix11=0
scale_bar=0
scale_bar_val=1.000000
scale=1
mode=1
fore=0
grid=0
volume=0
scroll=0
shift=1
shift_size=19.767442
fixed_pos=0.000000
ticker=1
ohlc=0
one_click=0
one_click_btn=1
bidline=1
askline=0
lastline=0
days=0
descriptions=0
tradelines=1
tradehistory=0
window_type=1
floating=0
background_color=0
foreground_color=16777215
barup_color=65280
bardown_color=65280
bullcandle_color=0
bearcandle_color=16777215
chartline_color=65280
volumes_color=3329330
grid_color=10061943
bidline_color=10061943
askline_color=255
lastline_color=49152
stops_color=255
windows_total=1

<window>
height=100.000000
objects=0

<indicator>
name=Main
path=
apply=1
show_data=1
scale_inherit=0
scale_line=0
scale_line_percent=50
scale_line_value=0.000000
scale_fix_min=0
scale_fix_min_val=0.000000
scale_fix_max=0
scale_fix_max_val=0.000000
expertmode=0
fixed_height=-1
</indicator>

<indicator>
name=Custom Indicator
path=Experts\new_me\new_me.ex5
apply=0
show_data=1
scale_inherit=0
scale_line=0
scale_line_percent=50
scale_line_value=0.000000
scale_fix_min=0
scale_fix_min_val=0.000000
scale_fix_max=0
scale_fix_max_val=0.000000
expertmode=4
fixed_height=-1

<graph>
name=
draw=0
style=0
width=1
color=
</graph>

<graph>
name=
draw=0
style=0
width=1
color=
</graph>

<graph>
name=
draw=0
style=0
width=1
color=
</graph>

<graph>
name=
draw=0
style=0
width=1
color=
</graph>

<graph>
name=
draw=0
style=0
width=1
color=
</graph>

<graph>
name=
draw=0
style=0
width=1
color=
</graph>

<graph>
name=
draw=0
style=0
width=1
color=
</graph>

<graph>
name=
draw=0
style=0
width=1
color=
</graph>

<graph>
name=
draw=0
style=0
width=1
color=
</graph>

<graph>
name=
draw=0
style=0
width=1
color=
</graph>

<graph>
name=
draw=0
style=0
width=1
color=
</graph>

<graph>
name=
draw=0
style=0
width=1
color=
</graph>

<graph>
name=
draw=0
style=0
width=1
color=
</graph>
<inputs>
═══ Notifications ═══=
EnableAlerts=true
EnablePush=true
EnableEmail=false
═══ Signals to fire ═══=
SignalM1=true
SignalM5=false
SignalM15=false
SignalM30=false
═══ Visual ═══=
LineWidth=2
DrawHistorical=true
ShowDashboard=true
═══ Debug ═══=
DebugMode=true
═══ Stack Quality Filter ═══=
UseStackFilter=true
MinStackScore=8
═══ Ribbon Spread Filter ═══=
UseSpreadFilter=true
MinSpreadPoints=0.0
MaxSpreadPoints=0.0
═══ Ribbon Slope Filter ═══=
UseSlopeFilter=true
SlopeLookback=5
MinSlopeThreshold=0.000001
═══ Pullback Zone Filter ═══=
UsePullbackFilter=false
MaxExtensionPct=0.005
═══ M1 Filter Overrides ═══=
M1IgnoreSpread=true
M1IgnoreSlope=false
═══ Signal Cooldown (bars) ═══=
CooldownBarsM1=5
CooldownBarsM5=3
CooldownBarsM15=3
CooldownBarsM30=3
═══ Daily Close Reference ═══=
ShowDailyCloseLine=true
DailyCloseLineColor=65535
</inputs>
</indicator>

<indicator>
name=Custom Indicator
path=Experts\new_me\exporter.ex5
apply=0
show_data=1
scale_inherit=0
scale_line=0
scale_line_percent=50
scale_line_value=0.000000
scale_fix_min=0
scale_fix_min_val=0.000000
scale_fix_max=0
scale_fix_max_val=0.000000
expertmode=4
fixed_height=-1

<graph>
name=Export
draw=0
style=0
width=1
color=
</graph>
<inputs>
ExportPrefix=asset_snapshot_
ExportOnEveryTick=true
</inputs>
</indicator>





</window>
</chart>
