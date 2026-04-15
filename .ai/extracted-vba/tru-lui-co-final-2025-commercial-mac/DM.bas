Option Explicit
Sub sumifDM()
Dim sumRange, criteria1, criteria2 As Range
Dim i, j, K6, total, lastRow, lastRowXK, lastCol As Long
With ThisWorkbook.Sheets("DM")
lastRow = .Cells(.Rows.Count, "F").End(xlUp).row
lastRowXK = ThisWorkbook.Sheets("XK").Cells(.Rows.Count, "AA").End(xlUp).row
lastCol = .Cells(6, Columns.Count).End(xlToLeft).Column
Set sumRange = ThisWorkbook.Sheets("XK").Range("AA11:AA" & lastRowXK)
Set criteria1 = ThisWorkbook.Sheets("XK").Range("U11:U" & lastRowXK)
Set criteria2 = ThisWorkbook.Sheets("XK").Range("B11:B" & lastRowXK)

Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel
On Error GoTo lbFinally ' khi co loi xay ra


' tinh sum if
    For j = 12 To lastCol
        For i = 7 To lastRow
            .Cells(i, j) = Round((Application.WorksheetFunction.SumIfs(sumRange, _
            criteria1, .Range("A" & i), criteria2, .Cells(6, j))) * .Range("I" & i), 2)
        Next
    Next
 ' tính tong
    For i = 7 To lastRow
     total = 0
        For j = 12 To lastCol
            total = total + .Cells(i, j)
        Next
        .Range("K" & i) = total
    Next
    'tinh K6
    K6 = ""
    If .Range("M6") <> "" Then
        For j = 12 To lastCol
            K6 = K6 & .Cells(6, j)
         Next
    .Range("K6") = "'" & K6 ' chuyen sang chuoi gop nhieu tk vao 1 bo CO
    Else: .Range("K6") = .Range("L6") ' 1 tk = 1 CO
    End If
    
    ThisWorkbook.Sheets("NK2").Range("V3") = .Range("K6") ' de tinh cong don or tru don
    ThisWorkbook.Sheets("Xuat").Range("B1") = .Range("K6") ' de tinh sumproduct
  
     
    

    
    
lbFinally:    ' hoan tra ve ban dat
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic


End With

End Sub

Sub deleteDM()
Dim lastRow, lastCol As Long
With ThisWorkbook.Sheets("DM")
lastRow = .Cells(.Rows.Count, "F").End(xlUp).row
lastCol = .Cells(6, Columns.Count).End(xlToLeft).Column

Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel
On Error GoTo lbFinally ' khi co loi xay ra
    ThisWorkbook.Sheets("DM").UsedRange ' giúp code chay nhanh hon
    ThisWorkbook.Sheets("DM").Range("K6:U" & lastRow).ClearContents
    
    
lbFinally: ' hoan tra ve ban dau
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
        
End With
End Sub
