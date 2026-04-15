Option Explicit

Sub truLuiArr()
    Dim wsXN As Worksheet, wsTruLui As Worksheet, wsNK As Worksheet
    Dim lookupRange As Range
    Dim i As Long, j As Long, h As Long, x As Long, lastRowXN As Long, lastRowOut As Long, lastRowNK As Long, lastRowTrului As Long
    Dim d As Variant, k As Double, l As Double, stt As Long, idx As Long
    Dim arrXN As Variant, arrNK As Variant
    Dim dictNK As Object, keyDictNK As Variant, keyTrului As Variant
    
    Application.ScreenUpdating = False
    Application.DisplayAlerts = False
    Application.EnableEvents = False
    Application.Calculation = xlCalculationManual
    
    Set dictNK = CreateObject("Scripting.Dictionary")

    Set wsXN = ThisWorkbook.Sheets("X-N")
    Set wsTruLui = ThisWorkbook.Sheets("Tru lui")
    Set wsNK = ThisWorkbook.Sheets("NK")

    lastRowXN = wsXN.Cells(wsXN.Rows.Count, "A").End(xlUp).row
    lastRowOut = wsTruLui.Cells(wsTruLui.Rows.Count, "A").End(xlUp).row + 1 ' gom lai 1 lastrow chung cho tung cot data
    x = lastRowOut
    stt = 1
    lastRowNK = wsNK.Cells(wsNK.Rows.Count, "A").End(xlUp).row
    
    arrXN = wsXN.Range("A4:V" & lastRowXN)
    arrNK = wsNK.Range("A11:BB" & lastRowNK)
       
    Dim Tongsldung As Double
    Tongsldung = 0
    For i = 1 To UBound(arrXN, 1)
    
        If arrXN(i, 22) > 0 Then 'Val() có nhiem vu chuyen doi mot chuoi (hoac bat ky giá tri nào) thành sô (kieu Double).
           
            If arrXN(i, 3) <> "" Then
                d = CleanString(arrXN(i, 1)) & CleanString(arrXN(i, 4)) & CleanString(arrXN(i, 5)) 'tkn ' So tkx&stt&mă tkn
            Else
                d = CleanString(arrXN(i, 1)) & CLng(arrXN(i, 2)) & CleanString(arrXN(i, 4)) & CleanString(arrXN(i, 5)) 'tkn ' So tkx&stt&mă tkn
            End If
                
            k = arrXN(i, 11) ' sl tôn
            l = arrXN(i, 22) ' sl su dung
            Tongsldung = Tongsldung + l

            With wsTruLui ' dung phuong phap gán giá tri thay v́ copy paste
                .Cells(lastRowOut, "A").Value = stt
                .Cells(lastRowOut, "B").Value = arrXN(i, 7) ' tên
                .Cells(lastRowOut, "C").Value = arrXN(i, 6) 'HS code
                .Cells(lastRowOut, "D").Value = arrXN(i, 1) ' sô tk
                .Cells(lastRowOut, "E").Value = arrXN(i, 2) 'ngày tk
                .Cells(lastRowOut, "F").Value = arrXN(i, 14) 'sô inv
                .Cells(lastRowOut, "G").Value = arrXN(i, 15) ' ngày inv
                .Cells(lastRowOut, "H").Value = arrXN(i, 5) ' mă nvl
                .Cells(lastRowOut, "I").Value = arrXN(i, 4) ' stt ḍng hàng
                .Cells(lastRowOut, "J").Value = arrXN(i, 12) ' dvt
                '.Cells(lastRowOut, "K").Value = Application.IfError(Application.VLookup(d, lookupRange, 13, False), "") ' nhâp ban dau
                .Cells(lastRowOut, "L").Value = arrXN(i, 17) ' SL da xuât
                .Cells(lastRowOut, "M").Value = k ' SL c̣n lai( tôn)
                .Cells(lastRowOut, "N").Value = l ' SL xuât dot này
                .Cells(lastRowOut, "O").Value = k - l ' SL c̣n lai dot sau
                .Cells(lastRowOut, "P").Value = arrXN(i, 18) ' So tkx
                .Cells(lastRowOut, "Q").Value = d
                
            End With

            stt = stt + 1
            lastRowOut = lastRowOut + 1
        End If
    Next i
    
    
     'ktra doi chieu tông sl dùng save & XN
    If Tongsldung = wsXN.Range("V1") Then
        MsgBox "SL su dung cua Trului khop! " & Tongsldung, vbInformation
    Else
        MsgBox "SL su dung cua Trului không khop, Hay kiem tra lai nhé! " & Tongsldung, vbInformation
    End If

    ' Đ?nh d?ng l?i vùng d? li?u
    With wsTruLui.Range("A4:O" & lastRowOut - 1)
        .Font.ColorIndex = 1
        .Interior.Color = RGB(255, 255, 255)
    End With
    
      ' kiêm tra sô tôn âm
    ' do data có sô tôn = 0 vào mang
    Dim arrTon0 As Variant
    Dim arrTrului As Variant
    Dim demDong As Long
    
    lastRowTrului = wsTruLui.Cells(wsTruLui.Rows.Count, "A").End(xlUp).row
    arrTrului = wsTruLui.Range("A7:Q" & lastRowTrului).Value
    
    ' === Đ?M S? D̉NG TH?A ĐI?U KI?N ===
    demDong = 0
    For i = 1 To UBound(arrTrului, 1)
        If Not IsError(arrTrului(i, 17)) And Trim(arrTrului(i, 17) & "") <> "" And Not IsError(arrTrului(i, 15)) And IsNumeric(arrTrului(i, 15)) And CDbl(arrTrului(i, 15)) = 0 Then
            demDong = demDong + 1
        End If
    Next i
    
        '=== T?O M?NG K?T QU? - S?A T?I ĐÂY ===
    If demDong > 0 Then
        ReDim arrTon0(1 To demDong, 1 To 18)
    Else
        ReDim arrTon0(1 To 1, 1 To 18)  ' T?o m [...]
        ' Ho?c t?t hon: dùng m?ng r?ng th?t s?
        arrTon0 = Array()  ' M?ng r?ng hoàn toàn (khuyên dùng)
    End If
    
    idx = 0
    If demDong > 0 Then
        For i = 1 To UBound(arrTrului, 1)
            If Not IsError(arrTrului(i, 17)) And Trim(arrTrului(i, 17) & "") <> "" And Not IsError(arrTrului(i, 15)) And IsNumeric(arrTrului(i, 15)) And CDbl(arrTrului(i, 15)) = 0 Then
                idx = idx + 1
                For j = 1 To 17
                    arrTon0(idx, j) = arrTrului(i, j)
                Next j
                arrTon0(idx, 18) = i + 6
            End If
        Next i
    End If
    
    
    ' -------- tao DICTNK------------'.Cells(lastRowOut, "K").Value = Application.IfError(Application.VLookup(d, lookupRange, 13, False), "") '
    For i = 1 To UBound(arrNK, 1)
        keyDictNK = Trim(CStr(arrNK(i, 15))) 'côt mă
        If Not dictNK.Exists(keyDictNK) Then
            dictNK.Add keyDictNK, arrNK(i, 27) ' côt sl
        Else
            dictNK(keyDictNK) = arrNK(i, 27) ' ghi dè
        End If
    Next i
    
      
    'dien côt sl nhâp ban dau
     ' B?t d?u di?n t? ḍng startRowGhi (trong sheet), tuong ?ng v?i i = ? trong m?ng
    Dim y As Long
    Dim row As Long
    y = lastRowOut - 1
    
    For row = x To y
        idx = row - 6  ' CHUY?N Đ?I: ḍng sheet ? ch? s? m?ng
        keyTrului = Trim(CStr(arrTrului(idx, 17))) 'côt mă
        If idx >= 1 And idx <= UBound(arrTrului, 1) Then
            If keyTrului <> "" And dictNK.Exists(keyTrului) Then
                wsTruLui.Cells(row, "K").Value = dictNK(keyTrului)
            Else
                wsTruLui.Cells(row, "K").Value = ""
            End If
        End If
    Next row
    

' === KI?M TRA TRÙNG: arrTon0 vs arrTrului (t? ḍng sau) - HI?N T?T C? ===
Dim logTrung As String
Dim foundDuplicate As Boolean
foundDuplicate = False
logTrung = ""

If Not IsEmpty(arrTon0) Then
    Dim dongGoc As Long
    Dim giaTriQ As Variant
    
    For i = 1 To UBound(arrTon0, 1)
        giaTriQ = arrTon0(i, 17)
        dongGoc = arrTon0(i, 18)
        
        If giaTriQ <> "" Then
            For h = 1 To UBound(arrTrului, 1)
                If (h + 6) > dongGoc Then
                    If arrTrului(h, 17) = giaTriQ Then
                        foundDuplicate = True
                        logTrung = logTrung & "• Ḍng " & dongGoc & " ? trùng ḍng " & (h + 6) & _
                                  " (giá tri: """ & giaTriQ & """)" & vbCrLf
                    End If
                End If
            Next h
        End If
    Next i
End If

' === HIÊN KÊT QUA ===
If foundDuplicate Then
    MsgBox "PHÁT HIÊN " & UBound(Split(logTrung, vbCrLf)) - 1 & " BI TRÙNG!" & vbCrLf & vbCrLf & _
           logTrung, vbCritical, "LÔI DATA"
Else
    MsgBox "Không có DATA nào bi trùng!", vbInformation, "KIÊM TRA HOÀN TÂT"
End If


' === ĐÔI CHIÊU SÔ D̉NG O SAVE VÀ TRU LÙI ===
' Đem so ḍng thoa dieu kien de xác dinh kích thuoc outputArr
    Dim cnt As Long
    cnt = 0
    For i = 1 To UBound(arrXN, 1)
        If arrXN(i, 22) > 0 Then cnt = cnt + 1 ' Cot V là cot 22
    Next i

 ' so sánh
    If stt - 1 = cnt Then
        MsgBox "Sô ḍng Save & Tru lùi khop!" & stt - 1 & " ḍng.", vbInformation
    Else
        MsgBox "Sô ḍng Save & Tru lùi không khop!" & "Save có " & cnt & " ; Tru lùi có " & stt - 1, vbInformation
    End If




lbFinally:
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic
End Sub

Function CleanString(txt As Variant) As String
    If IsError(txt) Or IsEmpty(txt) Then
        CleanString = ""
    Else
        CleanString = Trim(Replace(CStr(txt), Chr(160), ""))
    End If
End Function
