#!/usr/bin/env python3
"""Demo script for Life Navigation Phase 3: Monte Carlo Scenarios.

Shows all three template scenarios with realistic examples.
Run with: python3 demo_life_nav.py
"""

from life_nav_scenarios import ScenarioLibrary, GoalCategory

def print_section(title):
    """Print a formatted section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def print_metric(name, value, unit="", range_data=None):
    """Print a formatted metric."""
    if range_data:
        print(f"  {name:30} {value:8.1f} {unit:8} (range: {range_data[0]:6.1f}-{range_data[1]:6.1f})")
    else:
        print(f"  {name:30} {value:8.1f} {unit}")

def main():
    """Run all scenario demos."""
    
    # =========================================================================
    # SCENARIO 1: TRAINING GOAL — Can I maintain 5h/week for 12 weeks?
    # =========================================================================
    print_section("SCENARIO 1: TRAINING GOAL — 12-Week Training Plan")
    
    print("\n📊 Input:")
    print("  Current training:  4.5 hours/week")
    print("  Target training:   5.5 hours/week")
    print("  Duration:          12 weeks")
    print("  Variables:         adherence, recovery factors, weekly variations")
    
    scenario = ScenarioLibrary.create_training_goal_scenario(
        current_hours_per_week=4.5,
        target_hours_per_week=5.5,
        weeks=12,
    )
    scenario.run_simulation()
    
    print("\n📈 Monte Carlo Results (1000 samples):")
    
    success_chart = scenario.get_fan_chart("success_probability")
    print_metric("Success Probability", success_chart['median'], "%",
                (success_chart['min'], success_chart['max']))
    
    total_hours_chart = scenario.get_fan_chart("total_hours")
    print_metric("Total Hours", total_hours_chart['median'], "hours",
                (total_hours_chart['p25'], total_hours_chart['p75']))
    
    fitness_chart = scenario.get_fan_chart("fitness_improvement_pct")
    print_metric("Fitness Improvement", fitness_chart['median'], "%",
                (fitness_chart['min'], fitness_chart['max']))
    
    print("\n🎯 Sensitivity Analysis (What moves the needle?):")
    sensitivity = scenario.sensitivity_analysis()
    for var, corr in sorted(sensitivity.items(), key=lambda x: abs(x[1]), reverse=True):
        impact_level = "★★★" if abs(corr) > 0.7 else "★★" if abs(corr) > 0.4 else "★"
        direction = "↑ increases" if corr > 0 else "↓ decreases"
        print(f"  {var:25} {corr:+.3f}  {impact_level}  {direction}")
    
    print("\n💡 Recommendation:")
    if success_chart['median'] >= 70:
        print(f"  ✅ FEASIBLE — {success_chart['median']:.0f}% success probability")
        print(f"     You can sustain 5.5h/week for 12 weeks")
        print(f"     Protecting {sensitivity[max(sensitivity, key=lambda x: abs(sensitivity[x]))]:.0f}% adherence is critical")
    elif success_chart['median'] >= 40:
        print(f"  ⚠️  CHALLENGING — {success_chart['median']:.0f}% success probability")
        print(f"     Consider reducing target to 4.5h/week or extending timeline")
    else:
        print(f"  ❌ HIGH RISK — {success_chart['median']:.0f}% success probability")
        print(f"     Target is likely unachievable; reduce by 1-2 hours/week")
    
    # =========================================================================
    # SCENARIO 2: PROJECT GOAL — Can I finish the terrace?
    # =========================================================================
    print_section("SCENARIO 2: PROJECT GOAL — Terrace Renovation")
    
    print("\n📊 Input:")
    print("  Project size:      40 hours")
    print("  Available time:    5 hours/week")
    print("  Scope risk:        20% (typical risk of scope creep)")
    print("  Variables:         weekly hours variation, completion rate, scope changes")
    
    scenario = ScenarioLibrary.create_project_goal_scenario(
        project_size_hours=40,
        available_weekly_hours=5,
        risk_factor=0.2,
    )
    scenario.run_simulation()
    
    print("\n📈 Monte Carlo Results (1000 samples):")
    
    weeks_chart = scenario.get_fan_chart("weeks_to_completion")
    print_metric("Weeks to Completion", weeks_chart['median'], "weeks",
                (weeks_chart['p25'], weeks_chart['p75']))
    
    completion_chart = scenario.get_fan_chart("completion_probability")
    print_metric("6-Month Completion", completion_chart['median'], "%",
                (completion_chart['min'], completion_chart['max']))
    
    slack_chart = scenario.get_fan_chart("slack_weeks")
    print_metric("Schedule Slack", slack_chart['median'], "weeks",
                (slack_chart['min'], slack_chart['max']))
    
    print("\n🎯 Sensitivity Analysis:")
    sensitivity = scenario.sensitivity_analysis()
    for var, corr in sorted(sensitivity.items(), key=lambda x: abs(x[1]), reverse=True):
        impact_level = "★★★" if abs(corr) > 0.7 else "★★" if abs(corr) > 0.4 else "★"
        print(f"  {var:25} {corr:+.3f}  {impact_level}")
    
    print("\n💡 Recommendation:")
    if completion_chart['median'] >= 80:
        print(f"  ✅ VERY LIKELY — {completion_chart['median']:.0f}% within 6 months")
        print(f"     Median timeline: {weeks_chart['median']:.1f} weeks")
        print(f"     Plan for {weeks_chart['p75']:.0f} weeks to be safe")
    elif completion_chart['median'] >= 50:
        print(f"  ⚠️  FEASIBLE — {completion_chart['median']:.0f}% within 6 months")
        print(f"     Timeline: {weeks_chart['p25']:.0f}-{weeks_chart['p75']:.0f} weeks")
        print(f"     Add contingency buffer")
    else:
        print(f"  ❌ CHALLENGING — {completion_chart['median']:.0f}% within 6 months")
        print(f"     Increase availability to 6-7h/week or extend deadline")
    
    # =========================================================================
    # SCENARIO 3: LIFE BALANCE — Can I do both without burning out?
    # =========================================================================
    print_section("SCENARIO 3: LIFE BALANCE — Training + Projects")
    
    print("\n📊 Input:")
    print("  Weekly training:   4 hours")
    print("  Weekly projects:   6 hours")
    print("  Available time:    50 hours/week (work + personal)")
    print("  Variables:         weekly variations, stress sensitivity")
    
    scenario = ScenarioLibrary.create_balance_goal_scenario(
        training_hours_week=4,
        project_hours_week=6,
        max_weekly_hours=50,
    )
    scenario.run_simulation()
    
    print("\n📈 Monte Carlo Results (1000 samples):")
    
    feasibility_chart = scenario.get_fan_chart("feasibility_probability")
    print_metric("Sustainability", feasibility_chart['median'], "%",
                (feasibility_chart['min'], feasibility_chart['max']))
    
    stress_chart = scenario.get_fan_chart("stress_score")
    print_metric("Stress Level", stress_chart['median'], "/100",
                (stress_chart['min'], stress_chart['max']))
    
    load_chart = scenario.get_fan_chart("load_ratio")
    print_metric("Load Ratio", load_chart['median'], "ratio",
                (load_chart['min'], load_chart['max']))
    
    print("\n🎯 Sensitivity Analysis:")
    sensitivity = scenario.sensitivity_analysis()
    for var, corr in sorted(sensitivity.items(), key=lambda x: abs(x[1]), reverse=True):
        impact_level = "★★★" if abs(corr) > 0.7 else "★★" if abs(corr) > 0.4 else "★"
        print(f"  {var:25} {corr:+.3f}  {impact_level}")
    
    print("\n💡 Recommendation:")
    load = 4 + 6  # training + projects
    capacity = 50
    utilization = (load / capacity) * 100
    
    if feasibility_chart['median'] >= 80:
        print(f"  ✅ SUSTAINABLE — {feasibility_chart['median']:.0f}% feasibility")
        print(f"     Load: {load}h / {capacity}h capacity ({utilization:.0f}% utilization)")
        print(f"     Stress: {stress_chart['median']:.0f}/100 (healthy)")
        print(f"     You can maintain this balance long-term")
    elif feasibility_chart['median'] >= 50:
        print(f"  ⚠️  CHALLENGING — {feasibility_chart['median']:.0f}% feasibility")
        print(f"     Load: {load}h / {capacity}h capacity ({utilization:.0f}% utilization)")
        print(f"     Stress: {stress_chart['median']:.0f}/100 (moderate risk)")
        print(f"     Monitor closely; reduce one domain if stress increases")
    else:
        print(f"  ❌ OVERLOADED — {feasibility_chart['median']:.0f}% feasibility")
        print(f"     Load: {load}h / {capacity}h capacity ({utilization:.0f}% utilization)")
        print(f"     Stress: {stress_chart['median']:.0f}/100 (high risk)")
        print(f"     Reduce training to 3h OR projects to 5h")
    
    # =========================================================================
    # SUMMARY
    # =========================================================================
    print_section("SUMMARY")
    print("""
🔬 What We've Shown:
  1. TRAINING: Can you sustain higher volume for 12 weeks?
     → Sensitivity ranking helps prioritize (adherence, recovery)
  
  2. PROJECT: Will you finish before the deadline?
     → Fan charts show realistic timeline with confidence intervals
  
  3. BALANCE: Can you maintain multiple goals without burnout?
     → Stress modeling predicts overload risk

🎯 Key Insights:
  • Monte Carlo finds the realistic median (not best/worst case)
  • Sensitivity analysis identifies critical success factors
  • Fan charts (p25-p75) show the likely range, not outliers
  • Recommendations are tailored to success probability

💡 Use Cases:
  ✓ "Should I increase training target this month?"
  ✓ "Can I realistically finish this project by June?"
  ✓ "What if I add a second major project?"
  ✓ "Which change would have the most impact?"

🚀 Next Steps:
  • Integrate into REST API (/api/v1/life-nav/scenarios)
  • Store scenarios in database (track over time)
  • Add more template scenarios (financial, health, relationships)
  • Enable AI-generated recommendations based on patterns
""")
    print("=" * 80)

if __name__ == "__main__":
    main()
